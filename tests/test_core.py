import copy
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import wave
import zipfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
import numpy as np
from PIL import Image
from diadoris.model import Project,Slide,Clip,Title,Element,GRADIENTS,save_project,load_project,backup_project
from diadoris.render import Renderer,envelope,linear_blend
from diadoris.audio import mix_audio,duck_gain,RATE
from diadoris.video import inspect_video
from diadoris.export import export_project,ExportSettings
from transcora.core.engine import Cancelled,methods
from transcora.core.toolchain import Toolchain

APP=QApplication.instance() or QApplication([])


class ProjectTests(unittest.TestCase):
    def test_import_markers_match_transcora_and_jps_order(self):
        p=Project()
        for name,layout,swap in [('photo.jps','full_sbs',True),('photo-lr.jps','full_sbs',False),('film-lrq.mp4','half_sbs',False),('film.3D.HTAB.mkv','half_ou',False),('photo_sbs.jpg','full_sbs',False)]:
            resource=p.add_resource(name)
            self.assertEqual((resource.layout,resource.swap),(layout,swap))
    def test_centered_transition_preserves_duration_and_endpoints(self):
        p=Project(width=160,height=90,slides=[Slide(kind='black',duration=8) for _ in range(3)])
        self.assertEqual(p.duration,24)
        self.assertEqual(list(p.starts().values()),[0,8,16])
        self.assertEqual(p.transition_lengths(),[.5,.5])
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/'a.png';b=Path(temp)/'b.png'
            Image.new('RGB',(160,90),'red').save(a);Image.new('RGB',(160,90),'blue').save(b)
            p.slides=[Slide(resource=p.add_resource(a).id,duration=8),Slide(resource=p.add_resource(b).id,duration=8)]
            r=Renderer(p)
            self.assertEqual(r.frame(7.7)[0].getpixel((50,50)),(255,0,0))
            self.assertEqual(r.frame(8.3)[0].getpixel((50,50)),(0,0,255))
            mid=r.frame(8)[0].getpixel((50,50));self.assertTrue(185<=mid[0]<=189);self.assertTrue(185<=mid[2]<=189)
    def test_fades_follow_effective_show_end(self):
        self.assertAlmostEqual(envelope(8.5,0,10,0,3),.5)
        self.assertEqual(envelope(10,0,10,0,3),0)
        self.assertAlmostEqual(envelope(.5,0,1,2,2),1)
    def test_project_and_portable_backup_collision_dedup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'one').mkdir();(root/'two').mkdir()
            a=root/'one/logo.png';b=root/'two/logo.png';Image.new('RGB',(20,20),'red').save(a);Image.new('RGB',(20,20),'blue').save(b)
            p=Project();r1=p.add_resource(a);r2=p.add_resource(b);r3=p.add_resource(a)
            p.slides=[Slide(resource=r.id) for r in [r1,r2,r3]]
            state=p.to_dict();save_project(p,root/'test.dido');loaded=load_project(root/'test.dido');self.assertEqual(loaded.to_dict(),state)
            backup_project(p,root/'project.zip');self.assertEqual(p.to_dict(),state)
            with zipfile.ZipFile(root/'project.zip') as z:
                self.assertEqual(len([x for x in z.namelist() if x.startswith('images/')]),2)
                z.extractall(root/'restore')
            restored=load_project(root/'restore/DiaDoris.dido');self.assertFalse(restored.missing())
            self.assertEqual(Renderer(restored,(20,20)).slide(restored.slides[1])[0].getpixel((5,5)),(0,0,255,255))
    def test_title_alpha_depth_and_source_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'logo.png';image=Image.new('RGBA',(40,20),(0,0,0,0));image.paste((255,255,255,255),(10,5,30,15));image.save(file)
            p=Project(width=200,height=100);r=p.add_resource(file,'graphic')
            e=Element(kind='graphic',resource=r.id,shadow=False,depth=-20)
            title=Title(elements=[e]);p.slides=[Slide(kind='title',title=title)]
            left,right=Renderer(p).title(title)
            self.assertEqual(left.getpixel((0,0))[3],0)
            self.assertAlmostEqual(left.getbbox()[0]-right.getbbox()[0],4)
            with Image.open(file) as check:self.assertEqual(check.size,(40,20))
    def test_original_gradient_values_unchanged(self):
        self.assertEqual(GRADIENTS[0][1:],('#1C1D1F','#0C0D0F'));self.assertEqual(len(GRADIENTS),12)
    def test_unused_resource_does_not_break_recovery_or_backup(self):
        p=Project(slides=[Slide(kind='black')]);p.add_resource('/missing/deleted.png')
        self.assertFalse(p.missing());self.assertFalse(p.to_dict()['resources'])


class AudioTests(unittest.TestCase):
    def make_wave(self,path,seconds,amplitude=.2):
        values=np.full((round(seconds*RATE),2),round(amplitude*32767),dtype='<i2')
        with wave.open(str(path),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(RATE);f.writeframes(values.tobytes())
    def test_duck_overlap_does_not_accumulate(self):
        gain=duck_gain(np.array([.25,1.5,2.5,5]),[(1,3,-12,.5,1),(2,4,-12,.5,1)])
        self.assertAlmostEqual(gain[1],10**(-12/20),places=5);self.assertAlmostEqual(gain[2],gain[1],places=5);self.assertEqual(gain[3],1)
    def test_mix_clip_gain_duck_and_fade_at_show_end(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);self.make_wave(path/'music.wav',4)
            p=Project(slides=[Slide(kind='black',duration=3)])
            music=p.add_resource(path/'music.wav','audio');voice=p.add_resource(path/'music.wav','audio')
            p.audio1=[Clip(anchor=p.slides[0].id,kind='audio',resource=music.id,fade_in=0,hold=3,fade_out=1)]
            p.audio2=[Clip(anchor=p.slides[0].id,kind='audio',resource=voice.id,offset=1,fade_in=0,hold=1,fade_out=0,gain_db=-6,duck=True,duck_lead=0,duck_release=0)]
            mix_audio(p,path/'mix.f32')
            data=np.fromfile(path/'mix.f32',dtype='<f4').reshape(-1,2)
            self.assertEqual(len(data),3*RATE)
            self.assertAlmostEqual(data[RATE//2,0],.2,places=3)
            expected=.2*10**(-12/20)+.2*10**(-6/20)
            self.assertAlmostEqual(data[RATE+RATE//2,0],expected,places=3)
            self.assertAlmostEqual(data[2*RATE+RATE//2,0],.1,places=3)
            self.assertLess(abs(data[-1,0]),.0001)


class ExportTests(unittest.TestCase):
    def probe(self,path):
        return json.loads(subprocess.check_output([str(Toolchain.find().ffprobe),'-v','error','-show_streams','-show_format','-of','json',str(path)]))
    def test_real_packed_anaglyph_and_interleaved_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=Image.new('RGB',(320,90),'red');image.paste('blue',(160,0,320,90));image.save(root/'pair.png')
            p=Project(width=160,height=90,start_fade=0,end_fade=0);r=p.add_resource(root/'pair.png',layout='full_sbs');p.slides=[Slide(resource=r.id,duration=.1)]
            for target in ['full_sbs','full_ou','half_sbs','half_ou','row_interleaved']:
                out=root/(target+'.mkv');export_project(p,out,ExportSettings(target=target,width=160,height=90,container='mkv',audio='none',quality=True))
                info=self.probe(out);v=info['streams'][0]
                expected=(320,90) if target=='full_sbs' else (160,180) if target=='full_ou' else (160,90)
                # Row-interleaved defaults must follow the selected output dimensions.
                self.assertEqual((v['width'],v['height']),expected)
            for method in methods():
                out=root/(method+'.mkv');export_project(p,out,ExportSettings(target='anaglyph',method=method,width=160,height=90,container='mkv',audio='none',quality=True))
                self.assertEqual(self.probe(out)['streams'][0]['pix_fmt'],'yuv444p')
    def test_video_trim_speed_stereo_original_audio_and_cuts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'clip.mp4';tools=Toolchain.find()
            subprocess.run([str(tools.ffmpeg),'-v','error','-f','lavfi','-i','color=red:s=160x90:r=30:d=2',
                            '-f','lavfi','-i','color=blue:s=160x90:r=30:d=2','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2',
                            '-filter_complex','[0:v][1:v]hstack[v]','-map','[v]','-map','2:a','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
            p=Project(width=160,height=90,start_fade=0,end_fade=0);r=p.add_resource(source,'video',layout='full_sbs');r.info=inspect_video(source)
            clip=Slide(kind='video',resource=r.id,source_in=.5,duration=1,transition='fade');p.slides=[Slide(kind='black',duration=.2),clip,Slide(kind='black',duration=.2)]
            self.assertEqual(p.transition_lengths(),[0,0])
            renderer=Renderer(p);left,right=renderer.frame(.7)
            first_reader=next(iter(renderer.readers.values()))
            second=copy.deepcopy(clip);second.id+='-second';p.slides.append(second)
            renderer.frame(1.5)
            self.assertEqual(len(renderer.readers),1);self.assertIsNone(first_reader.process)
            p.slides.pop();renderer.close()
            self.assertGreater(left.getpixel((50,50))[0],240);self.assertGreater(right.getpixel((50,50))[2],240)
            out=root/'show.mp4';export_project(p,out,ExportSettings(width=160,height=90,quality=True))
            info=self.probe(out);self.assertAlmostEqual(float(info['format']['duration']),1.4,delta=.05)
            self.assertTrue(any(s['codec_type']=='audio' for s in info['streams']))
    def test_cancel_and_existing_output_are_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/'show.mp4';out.write_bytes(b'original')
            p=Project(width=160,height=90,slides=[Slide(kind='black',duration=1)])
            with self.assertRaises(ValueError):export_project(p,out,ExportSettings(width=160,height=90,audio='none'))
            self.assertEqual(out.read_bytes(),b'original');out.unlink()
            cancel=threading.Event();cancel.set()
            with self.assertRaises(Cancelled):export_project(p,out,ExportSettings(width=160,height=90,audio='none'),cancel)
            self.assertFalse(out.exists());self.assertFalse(list(root.glob('.diadoris-*')))
    def test_lossless_rgb_handoff_to_original_bd_pipeline(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Project(width=160,height=90,slides=[Slide(kind='black',duration=.1)],start_fade=0,end_fade=0)
            seen=[]
            def inspect(tools,plan,cancel,emit,log):
                info=self.probe(plan.source);video=info['streams'][0]
                self.assertEqual(video['pix_fmt'],'bgr0');self.assertEqual(video['color_space'],'gbr')
                self.assertEqual(video['avg_frame_rate'],'24000/1001')
                self.assertEqual(plan.options.target,'bd3d');seen.append(plan)
            with patch('transcora.core.bd3d_export.BdTools.find',return_value=object()),patch('diadoris.export.execute',side_effect=inspect):
                export_project(p,Path(temp)/'test.iso',ExportSettings(target='bd3d',container='iso',audio='none',bitrate=40))
            self.assertEqual(len(seen),1)


if __name__=='__main__':unittest.main()
