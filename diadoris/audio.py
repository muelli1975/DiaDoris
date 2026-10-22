"""Shared offline/preview mix: 48 kHz stereo, explicit gains, bounded blocks."""
from pathlib import Path
import math
import subprocess
import tempfile
import threading
from contextlib import ExitStack
import numpy as np

from transcora.core.engine import Cancelled, stop_process
from transcora.core.toolchain import Toolchain, process_options

RATE=48000


def run_process(args,cancel=None):
    cancel=cancel or threading.Event()
    with tempfile.TemporaryFile() as errors:
        p=subprocess.Popen(list(map(str,args)),stdout=subprocess.DEVNULL,stderr=errors,**process_options())
        try:
            while p.poll() is None:
                if cancel.wait(.05):raise Cancelled()
            if p.returncode:
                errors.seek(0);raise ValueError(errors.read().decode('utf-8','replace')[-3000:])
        finally:stop_process(p)


def audio_duration(path,tools=None):
    import json
    tools=tools or Toolchain.find()
    p=subprocess.run([str(tools.ffprobe),'-v','error','-show_entries','format=duration:stream=codec_type,channels',
                      '-of','json',str(path)],capture_output=True,timeout=30,**process_options())
    if p.returncode:raise ValueError(p.stderr.decode('utf-8','replace'))
    info=json.loads(p.stdout)
    streams=[s for s in info['streams'] if s['codec_type']=='audio']
    if not streams:raise ValueError('No audio stream')
    return float(info['format']['duration']),streams[0].get('channels',2)


def duck_gain(times,windows):
    """Strongest active reduction wins. Overlaps never multiply reductions."""
    gain=np.ones(len(times),dtype=np.float32)
    for start,end,db,lead,release in windows:
        strength=np.zeros(len(times),dtype=np.float32)
        strength[(times>=start)&(times<end)]=1.
        if lead:
            mask=(times>=start-lead)&(times<start)
            strength[mask]=(times[mask]-(start-lead))/lead
        if release:
            mask=(times>=end)&(times<end+release)
            strength[mask]=1-(times[mask]-end)/release
        gain=np.minimum(gain,np.power(10.,db*strength/20).astype(np.float32))
    return gain


def mix_audio(project,destination,cancel=None,progress=lambda value:None):
    """Return float peak before clipping. File contains little endian float32 stereo."""
    cancel=cancel or threading.Event();tools=Toolchain.find()
    frames=max(1,round(project.duration*RATE));destination=Path(destination)
    tracks=[(1,c) for c in project.audio1 if not c.mute]+[(2,c) for c in project.audio2 if not c.mute]
    from .model import Clip
    for slide in project.slides:
        if slide.kind=='video' and not slide.video_mute and project.resource(slide.resource).info.get('audio'):
            tracks.append((3,Clip(anchor=slide.id,resource=slide.resource,kind='audio',source_in=slide.source_in,
                                  fade_in=slide.video_fade_in,fade_out=slide.video_fade_out,
                                  hold=max(0,slide.duration-slide.video_fade_in-slide.video_fade_out),gain_db=slide.video_gain_db)))
    with tempfile.TemporaryDirectory(prefix='diadoris-audio-') as temporary, ExitStack() as cleanup:
        decoded={}
        for index,(_,clip) in enumerate(tracks):
            if clip.resource not in decoded:
                path=Path(temporary)/f'{len(decoded)}.f32'
                run_process([tools.ffmpeg,'-v','error','-nostdin','-y','-i',project.resource(clip.resource).path,
                             '-map','0:a:0','-vn','-ar',str(RATE),'-ac','2','-f','f32le',path],cancel)
                length=path.stat().st_size//8
                decoded[clip.resource]=np.memmap(path,dtype='<f4',mode='r',shape=(length,2))
                cleanup.callback(decoded[clip.resource]._mmap.close)
            progress(index/max(1,len(tracks))*.2)
        active=[];windows=[];starts=project.starts()
        for track,c in tracks:
            data=decoded[c.resource];start=starts[c.anchor]+c.offset
            available=max(0,len(data)/RATE-c.source_in)
            end=min(project.duration,start+c.duration,start+available)
            if end<=max(0,start):continue
            active.append((track,c,data,start,end))
            if track==2 and c.duck:
                windows.append((max(0,start),end,c.duck_db,c.duck_lead,c.duck_release))
        peak=0.
        with destination.open('wb') as out:
            for pos in range(0,frames,RATE):
                if cancel.is_set():raise Cancelled()
                count=min(RATE,frames-pos)
                times=(pos+np.arange(count))/RATE
                block=np.zeros((count,2),dtype=np.float32)
                duck=duck_gain(times,windows)
                for track,c,data,start,end in active:
                    mask=(times>=start)&(times<end)
                    if not mask.any():continue
                    indices=np.rint((times[mask]-start+c.source_in)*RATE).astype('int64')
                    indices=np.clip(indices,0,len(data)-1)
                    effective=end-start
                    factor=min(1.,effective/(c.fade_in+c.fade_out)) if c.fade_in+c.fade_out else 1.
                    fi,fo=c.fade_in*factor,c.fade_out*factor
                    gain=np.full(mask.sum(),10**(c.gain_db/20),dtype=np.float32)
                    if fi:gain*=np.clip((times[mask]-start)/fi,0,1)
                    if fo:gain*=np.clip((end-times[mask])/fo,0,1)
                    if track==1:gain*=duck[mask]
                    block[mask]+=data[indices]*gain[:,None]
                peak=max(peak,float(np.max(np.abs(block))))
                # Float headroom remains intact for the meter and explicit export policy.
                out.write(block.astype('<f4').tobytes())
                progress(.2+.8*(pos+count)/frames)
    return peak


def pcm16(source,destination):
    """Preview audio format conversion only, no automatic gain adjustment."""
    with Path(source).open('rb') as src,Path(destination).open('wb') as dst:
        while data:=src.read(RATE*8):
            array=np.frombuffer(data,dtype='<f4')
            dst.write(np.rint(np.clip(array,-1,1)*32767).astype('<i2').tobytes())
