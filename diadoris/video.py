"""Short video inserts; exact source speed, explicit trims, bounded decode pipes."""
from pathlib import Path
import json
import subprocess
import threading
from fractions import Fraction
from PIL import Image
from transcora.core.toolchain import Toolchain,process_options
from transcora.core.engine import stop_process

VIDEO_EXTENSIONS={'.mp4','.mkv','.mov','.avi','.m4v','.mts','.m2ts','.webm','.wmv','.mpg','.mpeg'}


def inspect_video(path):
    tools=Toolchain.find()
    p=subprocess.run([str(tools.ffprobe),'-v','error','-show_streams','-show_format','-of','json',str(path)],
                     capture_output=True,timeout=30,**process_options())
    if p.returncode:raise ValueError(p.stderr.decode('utf-8','replace'))
    data=json.loads(p.stdout)
    v=next((s for s in data['streams'] if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic')),None)
    if not v:raise ValueError('No video stream')
    if v.get('color_transfer') in {'smpte2084','arib-std-b67'}:raise ValueError('HDR video is not supported in this SDR test version')
    duration=float(v.get('duration') or data['format'].get('duration') or 0)
    if duration<=0:raise ValueError('Video duration could not be determined')
    rotation=next((int(s.get('rotation',0)) for s in v.get('side_data_list',[]) if 'rotation' in s),0)
    w,h=v['width'],v['height']
    if rotation%180:w,h=h,w
    return {'duration':duration,'width':w,'height':h,'fps':v.get('avg_frame_rate','30'),
            'audio':any(s['codec_type']=='audio' for s in data['streams']),
            'transfer':v.get('color_transfer','bt709'),'primaries':v.get('color_primaries','bt709'),
            'matrix':v.get('color_space','bt709'),'range':v.get('color_range','tv'),
            'sar':v.get('sample_aspect_ratio','1:1')}


class VideoReader:
    def __init__(self,resource,size,fps,fit):
        self.resource=resource;self.size=size;self.fps=float(fps);self.fit=fit
        self.process=None;self.last=-1;self.frame=None;self.base=0

    def close(self):
        if self.process:
            stop_process(self.process)
            if self.process.stdout:self.process.stdout.close()
            self.process=None

    def get(self,seconds):
        index=max(0,round(seconds*self.fps))
        if self.frame is not None and index==self.last:return self.frame
        if self.process is None or index<self.last or index-self.last>4:
            self.close();self.start(index/self.fps);self.last=index-1
        count=self.size[0]*2*self.size[1]*3
        while self.last<index:
            data=bytearray()
            while len(data)<count:
                part=self.process.stdout.read(count-len(data))
                if not part:break
                data.extend(part)
            if len(data)!=count:
                raise ValueError('Video decoder ended before the selected clip end')
            packed=Image.frombytes('RGB',(self.size[0]*2,self.size[1]),bytes(data)).convert('RGBA')
            w,h=self.size
            self.frame=(packed.crop((0,0,w,h)),packed.crop((w,0,w*2,h)));self.last+=1
        return tuple(p.copy() for p in self.frame)

    def start(self,seconds):
        r=self.resource;w,h=self.size;info=r.info
        iw,ih=info['width'],info['height'];layout=r.layout
        ew,eh=(iw//2,ih) if layout.endswith('sbs') else (iw,ih//2) if layout.endswith('ou') else (iw,ih)
        sar=Fraction(info.get('sar','1:1').replace(':','/')) if info.get('sar','1:1') not in {'0:1','N/A'} else Fraction(1)
        dw=round(ew*float(sar)*(2 if layout=='half_sbs' else 1))
        dh=eh*(2 if layout=='half_ou' else 1)
        mode='increase' if self.fit=='crop' else 'decrease'
        size=f'scale={dw}:{dh},setsar=1,scale={w}:{h}:force_original_aspect_ratio={mode}:flags=lanczos,'
        size+=f'crop={w}:{h}' if self.fit=='crop' else f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black'
        # Standard SDR decode to a shared sRGB representation before compositing.
        transfer=info.get('transfer','bt709')
        transfer=transfer if transfer in {'bt709','iec61966-2-1','smpte170m','gamma22','gamma28','bt2020-10','bt2020-12'} else 'bt709'
        matrix=info.get('matrix','bt709');matrix=matrix if matrix in {'bt709','smpte170m','bt470bg','bt2020nc','gbr'} else 'bt709'
        prim=info.get('primaries','bt709');prim=prim if prim in {'bt709','smpte170m','bt470bg','bt2020'} else 'bt709'
        color=(f'zscale=matrixin={matrix}:transferin={transfer}:primariesin={prim}:'
               f'rangein={"full" if info.get("range")=="pc" else "limited"}:'
               'matrix=gbr:transfer=iec61966-2-1:primaries=bt709:range=full,format=gbrp16')
        xy=(ew,0) if layout.endswith('sbs') else (0,eh) if layout.endswith('ou') else (0,0)
        graph=f'[0:v:0]fps={self.fps},{color},split[a][b];[a]crop={ew}:{eh}:0:0,{size}[l];[b]crop={ew}:{eh}:{xy[0]}:{xy[1]},{size}[r];'
        graph+=('[r][l]' if r.swap else '[l][r]')+'hstack,format=rgb24[out]'
        args=[str(Toolchain.find().ffmpeg),'-v','error','-nostdin','-ss',str(seconds),'-i',r.path,
              '-filter_complex_threads','1','-filter_complex',graph,'-map','[out]','-an','-f','rawvideo','pipe:1']
        self.process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,**process_options())

    def __del__(self):self.close()
