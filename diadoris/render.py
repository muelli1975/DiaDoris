from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import io
import math
import numpy as np
from PIL import Image, ImageCms, ImageFilter, ImageOps
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass


def pil_to_qimage(image):
    image=image.convert('RGBA')
    return QImage(image.tobytes(),image.width,image.height,image.width*4,QImage.Format.Format_RGBA8888).copy()


def qimage_to_pil(image):
    image=image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes('RGBA',(image.width(),image.height()),bytes(image.constBits()),'raw','RGBA',image.bytesPerLine())


def normalize(image):
    image=ImageOps.exif_transpose(image)
    alpha=image.getchannel('A') if image.mode=='RGBA' else None
    profile=image.info.get('icc_profile')
    if profile:
        rgb=ImageCms.profileToProfile(image.convert('RGB'),ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                                     ImageCms.createProfile('sRGB'),outputMode='RGB')
        image=rgb.convert('RGBA')
        if alpha is not None:image.putalpha(alpha)
    else:image=image.convert('RGBA')
    return image


def fit_image(image, size, mode='fit', cx=.5, cy=.5):
    """Crop coordinates shared between eyes, with proportional resizing."""
    if mode=='crop':
        return ImageOps.fit(image,size,Image.Resampling.LANCZOS,centering=(cx,cy))
    scaled=ImageOps.contain(image,size,Image.Resampling.LANCZOS)
    result=Image.new('RGBA',size)
    result.alpha_composite(scaled,((size[0]-scaled.width)//2,(size[1]-scaled.height)//2))
    return result


def envelope(t,start,end,fade_in,fade_out):
    """Fades end at the effective, show-clipped endpoint."""
    if end<=start or t<start or t>=end:return 0.
    length=end-start
    factor=min(1.,length/(fade_in+fade_out)) if fade_in+fade_out else 1.
    fi,fo=fade_in*factor,fade_out*factor
    return min(1.,(t-start)/fi if fi else 1.,(end-t)/fo if fo else 1.)


_LINEAR=np.where(np.arange(256)/255<=.04045,np.arange(256)/255/12.92,((np.arange(256)/255+.055)/1.055)**2.4).astype('float32')


def linear_blend(a,b,weight):
    if weight<=0:return a.copy()
    if weight>=1:return b.copy()
    v=_LINEAR[np.asarray(a.convert('RGB'))]*(1-weight)+_LINEAR[np.asarray(b.convert('RGB'))]*weight
    v=np.where(v<=.0031308,v*12.92,1.055*np.power(v,1/2.4)-.055)
    return Image.fromarray(np.clip(np.rint(v*255),0,255).astype('uint8'),'RGB').convert('RGBA')


def text_bitmap(element, scale):
    font=QFont(element.font)
    font.setPixelSize(max(1,round(element.size*scale)))
    font.setBold(element.bold);font.setItalic(element.italic)
    metrics=QFontMetricsF(font)
    lines=element.text.splitlines() or [' ']
    widths=[metrics.horizontalAdvance(line) for line in lines]
    ow=element.outline*scale
    pad=math.ceil(max(ow+3,element.shadow_blur*scale*3+abs(element.shadow_offset)*scale+3))
    width=max(1,math.ceil(max(widths))+pad*2)
    height=max(1,math.ceil(metrics.height()*1.2*len(lines))+pad*2)
    image=QImage(width,height,QImage.Format.Format_RGBA8888);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path=QPainterPath()
    for i,(line,w) in enumerate(zip(lines,widths)):
        x=pad+({'left':0.,'right':max(widths)-w}.get(element.align,(max(widths)-w)/2))
        path.addText(x,pad+metrics.ascent()+i*metrics.height()*1.2,font,line)
    if ow:
        painter.setPen(QPen(QColor('black'),ow*2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor(element.color));painter.drawPath(path)
    else:painter.fillPath(path,QColor(element.color))
    painter.end()
    result=qimage_to_pil(image)
    if element.shadow:
        alpha=result.getchannel('A').filter(ImageFilter.GaussianBlur(element.shadow_blur*scale))
        alpha=alpha.point(lambda x:round(x*element.shadow_opacity))
        shadow=Image.new('RGBA',result.size,(0,0,0,0));shadow.putalpha(alpha)
        shifted=Image.new('RGBA',result.size)
        shifted.alpha_composite(shadow,(round(element.shadow_offset*scale),round(element.shadow_offset*scale)))
        shifted.alpha_composite(result);result=shifted
    bounds=result.getbbox()
    return result.crop(bounds) if bounds else Image.new('RGBA',(1,1))


class Renderer:
    def __init__(self,project,size=None):
        self.project=project;self.size=size or (project.width,project.height)
        self.cache=OrderedDict();self.rects={};self.readers={};self.fps=project.fps
        self.cache_bytes=0;self.cache_limit=(192 if self.size[0]<=960 else 512)*1024*1024

    @staticmethod
    def image_bytes(value):
        if isinstance(value,Image.Image):return value.width*value.height*len(value.getbands())
        return sum(Renderer.image_bytes(v) for v in value) if isinstance(value,(list,tuple)) else 0

    def close(self):
        for reader in self.readers.values():reader.close()
        self.readers.clear()

    def cached(self,key,loader):
        if key in self.cache:
            result=self.cache.pop(key);self.cache[key]=result;return result
        result=loader();size=self.image_bytes(result)
        if size<=self.cache_limit:
            self.cache[key]=result;self.cache_bytes+=size
        while len(self.cache)>18 or self.cache_bytes>self.cache_limit:
            _,removed=self.cache.popitem(last=False);self.cache_bytes-=self.image_bytes(removed)
        return result

    def pair(self,key):
        resource=self.project.resource(key)
        def load():
            with Image.open(resource.path) as source:
                first=normalize(source)
                second=None
                if source.format=='MPO' and getattr(source,'n_frames',1)>=2:
                    source.seek(1);second=normalize(source)
            if resource.right:
                with Image.open(resource.right) as source:second=normalize(source)
            if second is not None:pair=(first,second)
            elif resource.layout.endswith('sbs'):
                w,h=first.size
                if w%2:raise ValueError('SBS image width must be even')
                pair=(first.crop((0,0,w//2,h)),first.crop((w//2,0,w,h)))
                if resource.layout=='half_sbs':pair=tuple(p.resize((w,h),Image.Resampling.LANCZOS) for p in pair)
            elif resource.layout.endswith('ou'):
                w,h=first.size
                if h%2:raise ValueError('OU image height must be even')
                pair=(first.crop((0,0,w,h//2)),first.crop((0,h//2,w,h)))
                if resource.layout=='half_ou':pair=tuple(p.resize((w,h),Image.Resampling.LANCZOS) for p in pair)
            else:pair=(first,first.copy())
            if pair[0].size!=pair[1].size:raise ValueError('Stereo half-images must have matching dimensions')
            return pair[::-1] if resource.swap else pair
        # File mtimes prevent stale pixels after resource replacement.
        stamp=tuple((p,Path(p).stat().st_mtime_ns) for p in (resource.path,resource.right) if p)
        return self.cached(('pair',key,resource.layout,resource.swap,stamp),load)

    def element_images(self,e):
        scale=self.size[1]/self.project.height
        if e.kind=='text':
            image=self.cached(('text',repr(e),self.size),lambda:text_bitmap(e,scale))
            return image,image
        return tuple(p.resize((max(1,round(p.width*e.scale*scale)),max(1,round(p.height*e.scale*scale))),Image.Resampling.LANCZOS)
                     for p in self.pair(e.resource))

    def element_rect(self,e):
        images=self.element_images(e)
        w,h=max(p.width for p in images),max(p.height for p in images)
        return e.x*self.size[0]-w/2,e.y*self.size[1]-h/2,w,h

    def title(self,title):
        w,h=self.size
        if title.background=='image' and title.image:
            pair=tuple(fit_image(p,self.size,title.fit,title.crop_x,title.crop_y) for p in self.pair(title.image))
        elif title.background in {'gradient','solid'}:
            a=np.array([int(title.top[i:i+2],16) for i in (1,3,5)])
            b=np.array([int((title.bottom if title.background=='gradient' else title.top)[i:i+2],16) for i in (1,3,5)])
            t=np.linspace(0,1,h)[:,None,None]
            rgb=np.repeat(np.rint(a[None,None,:]*(1-t)+b[None,None,:]*t).astype('uint8'),w,axis=1)
            base=Image.fromarray(rgb,'RGB').convert('RGBA');pair=(base,base.copy())
        else:pair=(Image.new('RGBA',self.size),Image.new('RGBA',self.size))
        for e in title.elements:
            for eye,bitmap in enumerate(self.element_images(e)):
                shift=(-1 if eye==0 else 1)*e.depth*w/2000
                x=round(e.x*w-bitmap.width/2+shift);y=round(e.y*h-bitmap.height/2)
                pair[eye].alpha_composite(bitmap,(x,y))
        return pair

    def slide(self,slide,time=0):
        if slide.kind=='video':
            from .video import VideoReader
            key=(slide.id,self.size,self.fps)
            if key not in self.readers:self.readers[key]=VideoReader(self.project.resource(slide.resource),self.size,self.fps,slide.fit)
            pair=self.readers[key].get(slide.source_in+max(0,min(time,slide.duration-1e-6)))
            alpha=envelope(time,0,slide.duration,slide.video_fade_in,slide.video_fade_out)
            if alpha<1:
                black=Image.new('RGBA',self.size,'black')
                pair=tuple(linear_blend(black,x,alpha) for x in pair)
            return pair
        def load():
            if slide.kind=='title':pair=self.title(slide.title)
            elif slide.kind=='black':pair=(Image.new('RGBA',self.size,'black'),)*2
            else:pair=tuple(fit_image(p,self.size,slide.fit) for p in self.pair(slide.resource))
            result=[]
            for p in pair:
                base=Image.new('RGBA',self.size,'black');base.alpha_composite(p);result.append(base)
            return tuple(result)
        return self.cached(('slide',repr(slide),self.size),load)

    def frame(self,time):
        p=self.project;slides=p.slides
        if not slides:return (Image.new('RGB',self.size,'black'),)*2
        starts=p.starts();lengths=p.transition_lengths()
        t=max(0,min(time,max(0,p.duration-1e-9)))
        pair=None
        for i,length in enumerate(lengths):
            boundary=starts[slides[i+1].id]
            if length and boundary-length/2<=t<boundary+length/2:
                v=(t-boundary+length/2)/length
                a,b=self.slide(slides[i]),self.slide(slides[i+1])
                if slides[i].transition=='black':
                    black=Image.new('RGBA',self.size,'black')
                    pair=tuple(linear_blend(x,black,v*2) if v<.5 else linear_blend(black,y,(v-.5)*2) for x,y in zip(a,b))
                else:pair=tuple(linear_blend(x,y,v) for x,y in zip(a,b))
                break
        if pair is None:
            index=max(i for i,s in enumerate(slides) if starts[s.id]<=t)
            pair=tuple(x.copy() for x in self.slide(slides[index],t-starts[slides[index].id]))
        for clip in p.overlays:
            start,end=p.clip_window(clip)
            alpha=envelope(t,start,end,clip.fade_in,clip.fade_out)
            if not alpha:continue
            if clip.kind=='title':overlay=self.cached(('title',repr(clip.title),self.size),lambda:self.title(clip.title))
            else:overlay=self.cached(('overlay',clip.resource,self.size),lambda:tuple(fit_image(x,self.size) for x in self.pair(clip.resource)))
            for dst,src in zip(pair,overlay):
                if alpha<1:
                    src=src.copy();src.putalpha(src.getchannel('A').point(lambda v:round(v*alpha)))
                dst.alpha_composite(src)
        alpha=envelope(t,0,p.duration,min(p.start_fade,p.slides[0].duration),min(p.end_fade,p.slides[-1].duration))
        if alpha<1:
            black=Image.new('RGBA',self.size,'black')
            pair=tuple(linear_blend(black,x,alpha) for x in pair)
        return tuple(x.convert('RGB') for x in pair)


def preview_pair(pair,mode='anaglyph'):
    left,right=pair
    if mode in {'parallel','cross'}:
        if mode=='cross':left,right=right,left
        out=Image.new('RGB',(left.width*2,left.height));out.paste(left,(0,0));out.paste(right,(left.width,0));return out
    if mode=='left':return left.convert('RGB')
    # Exact established StereoFine/SplatTricia anaglyph implementation.
    from .anaglyph import make_anaglyph
    return Image.fromarray(make_anaglyph(np.asarray(left.convert('RGB')),np.asarray(right.convert('RGB'))),'RGB')
