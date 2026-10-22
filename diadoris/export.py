from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import math
import os
import subprocess
import tempfile
import threading
import time
import numpy as np

from transcora.core.engine import Cancelled, build_graph, methods, plan_job, execute, stop_process
from transcora.core.model import Options, Job
from transcora.core.toolchain import Toolchain, process_options
from transcora.core.mp4 import packed_stereo_boxes
from .audio import mix_audio
from .render import Renderer


@dataclass
class ExportSettings:
    target: str = 'full_sbs'
    width: int = 1920
    height: int = 1080
    fps: str = '30'
    bitrate: float = 20.
    crf: float = 18.
    quality: bool = False
    codec: str = 'h264'
    container: str = 'mp4'
    audio: str = 'aac'
    audio_bitrate: int = 320
    method: str = 'dubois_lcd'
    profile: str = 'quality'
    bd_mode: str = '1080p'
    clip_audio: bool = False


PRESETS = [
    ('Full-SBS · 1080p · MP4 · 20 Mbit/s', ExportSettings()),
    ('Full-SBS · 1080p · MKV · CRF 16 · FLAC', ExportSettings(container='mkv',quality=True,crf=16,audio='flac')),
    ('Full-SBS · 2160p · MKV · H.265 · CRF 18', ExportSettings(width=3840,height=2160,container='mkv',codec='h265',quality=True,audio='flac')),
    ('Half-SBS · 1080p · MP4 · 15 Mbit/s', ExportSettings(target='half_sbs',bitrate=15)),
    ('Half-OU · 1080p · MP4 · 15 Mbit/s', ExportSettings(target='half_ou',bitrate=15)),
    ('Anaglyph · 1080p · MKV · 4:4:4', ExportSettings(target='anaglyph',container='mkv',quality=True,audio='flac')),
    ('Blu-ray 3D · 1080p · ISO · 40 Mbit/s', ExportSettings(target='bd3d',container='iso',fps='24000/1001',bitrate=40,audio='pcm')),
    ('Blu-ray 3D · 1080p · M2TS · 40 Mbit/s', ExportSettings(target='bd3d',container='m2ts',fps='24000/1001',bitrate=40,audio='pcm')),
]


def options_for(settings):
    return Options(layout='full_sbs',target=settings.target,method=settings.method,profile=settings.profile,
                   container=settings.container,codec=settings.codec,rate_mode='crf' if settings.quality else 'abr',
                   crf=settings.crf,bitrate_mbps=settings.bitrate,video_size='original',fps_mode='source',
                   bd_bitrate_mbps=round(settings.bitrate),bd_mode=settings.bd_mode,
                   screen_width=settings.width,screen_height=settings.height)


def export_project(project,destination,settings,cancel=None,progress=lambda p:None):
    project.validate()
    if not project.slides:raise ValueError('The image sequence is empty')
    if project.missing():raise ValueError('Missing project resources')
    cancel=cancel or threading.Event();tools=Toolchain.find()
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Output already exists; choose another filename')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if settings.target=='bd3d':
        from transcora.core.bd3d import output_mode
        from transcora.core.bd3d_export import BdTools
        BdTools.find()  # Fail before rendering if the Windows tools are unavailable.
        width,height,rate=output_mode(settings.bd_mode)
    else:
        width,height,rate=settings.width,settings.height,Fraction(settings.fps)
    if width%2 or height%2 or not 16<=width<=7680 or not 16<=height<=4320:raise ValueError('Invalid export size')
    count=math.ceil(project.duration*float(rate)-1e-9)
    from transcora.core.model import app_root
    logdir=app_root()/'logs';logdir.mkdir(exist_ok=True)
    logpath=logdir/('DiaDoris-'+time.strftime('%Y%m%d-%H%M%S')+'.log')
    with tempfile.TemporaryDirectory(prefix='.diadoris-',dir=destination.parent) as temporary:
        folder=Path(temporary);audio=folder/'mix.f32'
        has_audio=settings.audio!='none' and (bool(project.audio1 or project.audio2) or any(s.kind=='video' and not s.video_mute and project.resource(s.resource).info.get('audio') for s in project.slides))
        if has_audio:
            peak=mix_audio(project,audio,cancel,lambda v:progress(v*10))
            if peak>1. and not settings.clip_audio:
                raise ValueError(f'Audio clipping: {20*math.log10(peak):.1f} dBFS. Lower clip gain or explicitly allow clipping.')
        source_video={'index':0,'width':width*2,'height':height,'pix_fmt':'rgb24','field_order':'progressive',
                      'time_base':str(1/rate),'avg_frame_rate':str(rate),'r_frame_rate':str(rate)}
        options=options_for(settings)
        if settings.target=='bd3d':
            intermediate=folder/'stereo.mkv'
            vf=None;pixel='bgr0';output=intermediate
        else:
            vf,_,pixel=build_graph(source_video,options,'full_sbs',False,
                                  {'matrix':'gbr','primaries':'bt709','transfer':'iec61966-2-1','range':'pc'},methods()[settings.method])
            output=folder/('movie.'+settings.container)
        args=[str(tools.ffmpeg),'-v','warning','-nostdin','-y','-threads','2','-f','rawvideo','-pixel_format','rgb24',
              '-video_size',f'{width*2}x{height}','-framerate',str(rate),'-i','pipe:0']
        if has_audio:args+=['-f','f32le','-ar','48000','-ac','2','-i',str(audio)]
        if vf:args+=['-filter_complex_threads','1','-filter_complex',vf,'-map','[v]']
        else:args+=['-map','0:v:0']
        if has_audio:args+=['-map','1:a:0']
        if settings.target=='bd3d':
            args+=['-c:v','ffv1','-level','3','-pix_fmt',pixel,'-color_range','pc','-color_trc','iec61966-2-1',
                   '-color_primaries','bt709','-colorspace','rgb','-c:a','pcm_s24le']
        else:
            args+=['-c:v','libx264' if settings.codec=='h264' else 'libx265','-preset','slow','-pix_fmt',pixel,
                   '-crf',str(settings.crf)] if settings.quality else [
                   '-c:v','libx264' if settings.codec=='h264' else 'libx265','-preset','slow','-pix_fmt',pixel,'-b:v',str(round(settings.bitrate*1000000))]
            args+=['-color_range','tv','-color_trc','bt709','-color_primaries','bt709','-colorspace','bt709']
            if has_audio:
                args+=['-c:a',settings.audio,'-ar','48000','-ac','2']
                args+=['-b:a',f'{settings.audio_bitrate}k','-profile:a','aac_low'] if settings.audio=='aac' else ['-sample_fmt','s32','-bits_per_raw_sample','24']
            mode={'full_sbs':'left_right','half_sbs':'left_right','full_ou':'top_bottom','half_ou':'top_bottom','row_interleaved':'row_interleaved_lr'}.get(settings.target)
            if mode:
                args+=['-metadata:s:v:0','stereo_mode='+mode]
                if settings.codec=='h264':args+=['-x264-params','frame-packing='+('2' if settings.target=='row_interleaved' else '3' if settings.target.endswith('sbs') else '4')]
            if settings.container=='mp4':args+=['-movflags','+faststart']
        args+=['-t',str(count/float(rate)),str(output)]
        with logpath.open('w',encoding='utf-8') as log,tempfile.TemporaryFile() as errors:
            import json
            log.write(json.dumps(args,ensure_ascii=False)+'\n');log.flush()
            p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=errors,**process_options())
            watchdog_done=threading.Event()
            def watchdog():
                while not watchdog_done.wait(.1):
                    if cancel.is_set():stop_process(p);return
            monitor=threading.Thread(target=watchdog,daemon=True);monitor.start()
            renderer=Renderer(project,(width,height))
            renderer.fps=str(rate)
            try:
                for n in range(count):
                    if cancel.is_set():raise Cancelled()
                    left,right=renderer.frame(n/float(rate))
                    packed=np.concatenate((np.asarray(left),np.asarray(right)),axis=1)
                    p.stdin.write(packed.tobytes())
                    if n%max(1,round(float(rate)/4))==0:progress(10+80*n/count)
                p.stdin.close()
                while p.poll() is None:
                    if cancel.wait(.1):raise Cancelled()
                errors.seek(0);text=errors.read().decode('utf-8','replace');log.write(text)
                if p.returncode:raise ValueError(text[-4000:])
            except OSError as error:
                stop_process(p)
                if cancel.is_set():raise Cancelled() from error
                errors.seek(0);detail=errors.read().decode('utf-8','replace')[-4000:];log.write(detail)
                if detail:raise ValueError(detail) from error
                raise
            finally:
                watchdog_done.set();stop_process(p);monitor.join(timeout=2)
                renderer.close()
                if not p.stdin.closed:p.stdin.close()
        if cancel.is_set():raise Cancelled()
        if settings.target=='bd3d':
            # Lossless preparation only; the original TransCora MVC path performs the final encode.
            bd_options=options_for(settings)
            plan=plan_job(tools,Job(source=intermediate,options=bd_options),destination.parent,set(),cancel)
            from dataclasses import replace
            plan=replace(plan,output=destination)
            execute(tools,plan,cancel,lambda kind,value:progress(90+value.get('percent',0)*.1) if kind=='progress' and isinstance(value,dict) else None,logpath)
        else:
            if not output.is_file() or output.stat().st_size==0:raise ValueError('No output video was created')
            if settings.container=='mp4':packed_stereo_boxes(output,normalize=True)
            # Same-filesystem hard link makes publication atomic and never overwrites.
            os.link(output,destination)
        progress(100.)
    return logpath
