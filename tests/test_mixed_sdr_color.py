"""Compare the same gray chart as photo and Rec.709 video in one actual show."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import QApplication
from diadoris.model import Project,Slide
from diadoris.render import Renderer
from diadoris.video import inspect_video
from diadoris.export import export_project,ExportSettings
from transcora.core.toolchain import Toolchain

APP=QApplication.instance() or QApplication([])


class MixedSDRTests(unittest.TestCase):
    def test_photo_video_preview_and_actual_export_match(self):
        tools=Toolchain.find()
        levels=[0,16,32,64,96,128,192,255]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);photo=root/"photo.png";video=root/"clip.mp4"
            eye=Image.new("RGB",(256,144))
            for i,g in enumerate(levels):eye.paste((g,g,g),(32*i,0,32*(i+1),144))
            pair=Image.new("RGB",(512,144));pair.paste(eye,(0,0));pair.paste(eye,(256,0));pair.save(photo)
            subprocess.run([str(tools.ffmpeg),"-v","error","-nostdin","-loop","1","-framerate","30","-i",str(photo),
                            "-vf","scale=in_range=full:out_range=limited:out_color_matrix=bt709,format=yuv420p,"
                            "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=limited",
                            "-frames:v","30","-c:v","libx264","-crf","18",str(video)],check=True)
            project=Project(width=256,height=144,start_fade=0,end_fade=0)
            still=project.add_resource(photo,layout="full_sbs")
            clip=project.add_resource(video,"video",layout="full_sbs");clip.info=inspect_video(video)
            project.slides=[Slide(resource=still.id,duration=.4),
                            Slide(kind="video",resource=clip.id,duration=.4),
                            Slide(resource=still.id,duration=.4)]
            renderer=Renderer(project)
            try:
                for t in (.2,.6,1.):
                    left,right=renderer.frame(t)
                    for i,g in enumerate(levels):
                        self.assertLessEqual(max(abs(v-g) for v in left.getpixel((32*i+16,72))[:3]),3,(t,g))
            finally:renderer.close()
            out=root/"show.mp4"
            export_project(project,out,ExportSettings(width=256,height=144,audio="none",quality=True))
            for t in (.2,.6,1.):
                raw=subprocess.check_output([str(tools.ffmpeg),"-v","error","-nostdin","-i",str(out),
                    "-ss",str(t),"-frames:v","1","-vf","scale=in_color_matrix=bt709:in_range=limited:out_range=full",
                    "-f","rawvideo","-pix_fmt","rgb24","pipe:1"])
                image=Image.frombytes("RGB",(512,144),raw)
                for i,g in enumerate(levels):
                    self.assertLessEqual(max(abs(v-g) for v in image.getpixel((32*i+16,72))),3,(t,g))


if __name__=="__main__":unittest.main()
