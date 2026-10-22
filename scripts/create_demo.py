"""Create small, original calibration media and an editable sample project."""
from pathlib import Path
import sys
import wave
import numpy as np
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from diadoris.model import Project,Slide,Clip,Title,Element,save_project


def main():
    folder=ROOT/'examples';folder.mkdir(exist_ok=True)
    for n,colors in enumerate([('#263d55','#a7c8d2'),('#4a3628','#dbc28e')],1):
        views=[]
        for eye in (0,1):
            image=Image.new('RGB',(960,540),colors[0]);d=ImageDraw.Draw(image)
            d.rectangle((70,70,890,470),outline=colors[1],width=2)
            for i in range(5):
                x=120+i*145+(1 if eye==0 else -1)*i*3
                d.rounded_rectangle((x,160+i*12,x+105,360+i*12),radius=10,fill=colors[1])
            views.append(image)
        packed=Image.new('RGB',(1920,540));packed.paste(views[0],(0,0));packed.paste(views[1],(960,0));packed.save(folder/f'stereo_{n}_sbs.png')
    logo=Image.new('RGBA',(240,160));d=ImageDraw.Draw(logo);d.ellipse((35,20,165,150),fill='#c6a95e');d.polygon([(90,50),(90,120),(145,85)],fill='#202020');logo.save(folder/'logo.png')
    seconds=5;phase=np.arange(48000*seconds)/48000
    sound=(np.sin(phase*2*np.pi*440)*.025*np.sin(np.minimum(phase,seconds-phase)*np.pi/2).clip(0,1)).astype('float32')
    with wave.open(str(folder/'tone.wav'),'wb') as f:
        f.setframerate(48000);f.setsampwidth(2);f.setnchannels(2);f.writeframes(np.repeat(np.rint(sound*32767).astype('<i2')[:,None],2,axis=1).tobytes())
    p=Project()
    p.slides=[Slide(name='Opening',kind='title',title=Title(background='gradient',elements=[Element(text='DiaDoris',size=120),Element(text='Stereoscopic slide shows',size=44,y=.62)]),duration=4)]
    for n in (1,2):
        r=p.add_resource(folder/f'stereo_{n}_sbs.png',layout='full_sbs');p.slides.append(Slide(name=f'Stereo {n}',resource=r.id,duration=6,transition_duration=1))
    p.slides.append(Slide(name='Black',kind='black',duration=2))
    r=p.add_resource(folder/'logo.png','graphic');title=Title(elements=[Element(text='A new perspective',size=80),Element(kind='graphic',resource=r.id,scale=.7,x=.5,y=.75,shadow=False)])
    p.overlays=[Clip(anchor=p.slides[1].id,name='Editable title + logo',title=title,fade_in=.5,hold=4,fade_out=.5)]
    r=p.add_resource(folder/'tone.wav','audio');p.audio1=[Clip(anchor=p.slides[0].id,name='Quiet calibration tone',kind='audio',resource=r.id,fade_in=.3,hold=4.2,fade_out=.5)]
    save_project(p,folder/'Example.dido')
    print(folder/'Example.dido')


if __name__=='__main__':main()
