from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import copy
import hashlib
import json
import math
import os
import tempfile
import uuid
import zipfile


def uid():
    return uuid.uuid4().hex


GRADIENTS = [
    ('Anthrazit', '#1C1D1F', '#0C0D0F'),
    ('Warmes Grau', '#201E1C', '#100F0E'),
    ('Nachtstahl', '#1A1F26', '#0A0C10'),
    ('Nachtblau', '#18202A', '#0B1016'),
    ('Bronze', '#221E1A', '#120F0C'),
    ('Bordeaux', '#23181C', '#120B0E'),
    ('Tiefes Grün-Schwarz', '#1B201D', '#0C100E'),
    ('Graphit', '#434343', '#000000'),
    ('Schwarz / Kupfer', '#0B0A09', '#3A2418'),
    ('Schwarz / Aubergine', '#0A080C', '#2A1A28'),
    ('Schwarz / Petrolgrün', '#0A0E0C', '#1F2E2A'),
    ('Seidenhell', '#E6E9F0', '#EEF1F5'),
]


@dataclass
class Resource:
    path: str
    kind: str = 'image'
    layout: str = 'mono'
    swap: bool = False
    right: str = ''
    info: dict = field(default_factory=dict)
    id: str = field(default_factory=uid)


@dataclass
class Element:
    kind: str = 'text'
    text: str = 'Titel'
    resource: str = ''
    x: float = .5
    y: float = .47
    depth: float = 0.
    font: str = 'Segoe UI'
    size: float = 72.
    bold: bool = False
    italic: bool = False
    color: str = '#FFFFFF'
    align: str = 'center'
    scale: float = 1.
    shadow: bool = True
    shadow_opacity: float = .6
    shadow_offset: float = 3.
    shadow_blur: float = 6.
    outline: float = 0.
    id: str = field(default_factory=uid)


@dataclass
class Title:
    background: str = 'transparent'
    top: str = '#1C1D1F'
    bottom: str = '#0C0D0F'
    image: str = ''
    fit: str = 'crop'
    crop_x: float = .5
    crop_y: float = .5
    elements: list[Element] = field(default_factory=lambda: [Element()])


@dataclass
class Slide:
    name: str = ''
    kind: str = 'image'
    resource: str = ''
    duration: float = 8.
    transition: str = 'fade'
    transition_duration: float = .5
    fit: str = 'fit'
    title: Title | None = None
    source_in: float = 0.
    video_gain_db: float = 0.
    video_mute: bool = False
    video_fade_in: float = 0.
    video_fade_out: float = 0.
    id: str = field(default_factory=uid)


@dataclass
class Clip:
    anchor: str = ''
    name: str = ''
    kind: str = 'title'
    resource: str = ''
    offset: float = 0.
    fade_in: float = .5
    hold: float = 5.
    fade_out: float = .5
    source_in: float = 0.
    gain_db: float = 0.
    mute: bool = False
    duck: bool = False
    duck_db: float = -12.
    duck_lead: float = .5
    duck_release: float = 1.
    title: Title | None = None
    id: str = field(default_factory=uid)

    @property
    def duration(self):
        return self.fade_in + self.hold + self.fade_out


def title_from(data):
    if data is None:
        return None
    return Title(**{**data, 'elements': [Element(**e) for e in data.get('elements', [])]})


@dataclass
class Project:
    width: int = 1920
    height: int = 1080
    fps: str = '30'
    default_duration: float = 8.
    default_transition: float = .5
    start_fade: float = .5
    end_fade: float = .5
    resources: list[Resource] = field(default_factory=list)
    slides: list[Slide] = field(default_factory=list)
    overlays: list[Clip] = field(default_factory=list)
    audio1: list[Clip] = field(default_factory=list)
    audio2: list[Clip] = field(default_factory=list)

    @property
    def duration(self):
        return sum(s.duration for s in self.slides)

    def starts(self):
        result, pos = {}, 0.
        for slide in self.slides:
            result[slide.id] = pos
            pos += slide.duration
        return result

    def resource(self, key):
        return next(r for r in self.resources if r.id == key)

    def add_resource(self, path, kind='image', layout=None):
        path = str(Path(path).resolve())
        swap=Path(path).stem.lower().endswith('-rl')
        if layout is None:
            stem = Path(path).stem.lower()
            from transcora.core.naming import filename_layout
            hint=filename_layout(stem)
            if hint and hint[0] in {'full_sbs','half_sbs','full_ou','half_ou'}:layout,swap=hint
            elif stem.endswith('_sbs'):layout='full_sbs'
            elif Path(path).suffix.lower() in {'.jps','.pns'}:layout,swap='full_sbs',True
            else:layout='mono'
        resource = Resource(path, kind=kind, layout=layout, swap=swap)
        self.resources.append(resource)
        return resource

    def clip_window(self, clip):
        start = self.starts()[clip.anchor] + clip.offset
        return start, min(self.duration, start + clip.duration)

    def to_dict(self):
        data=asdict(self)
        used=self.used_resources()
        data['resources']=[r for r in data['resources'] if r['id'] in used]
        return {'format': 'DiaDoris', 'schema': 1, **data}

    def used_resources(self):
        used=set()
        for o in self.slides+self.overlays+self.audio1+self.audio2:
            if o.resource:used.add(o.resource)
            if o.title:
                if o.title.image:used.add(o.title.image)
                used.update(e.resource for e in o.title.elements if e.resource)
        return used

    @classmethod
    def from_dict(cls, data):
        if data.get('format') != 'DiaDoris' or data.get('schema') != 1:
            raise ValueError('Unsupported DiaDoris project format')
        values = {k:v for k,v in data.items() if k not in {'format', 'schema'}}
        values['resources'] = [Resource(**r) for r in values.get('resources', [])]
        values['slides'] = [Slide(**{**s, 'title': title_from(s.get('title'))}) for s in values.get('slides', [])]
        for track in ('overlays', 'audio1', 'audio2'):
            values[track] = [Clip(**{**c, 'title': title_from(c.get('title'))}) for c in values.get(track, [])]
        project = cls(**values)
        project.validate()
        return project

    def validate(self):
        from fractions import Fraction
        if not (16 <= self.width <= 7680 and 16 <= self.height <= 4320 and self.width%2 == self.height%2 == 0):
            raise ValueError('Project dimensions must be even and between 16 and 7680 × 4320')
        rate = Fraction(self.fps)
        if not 1 <= rate <= 120:
            raise ValueError('Invalid frame rate')
        resources = {r.id for r in self.resources}
        ids = [s.id for s in self.slides]
        if len(ids) != len(set(ids)) or len(resources) != len(self.resources):
            raise ValueError('Duplicate project identifiers')
        def number(x, lo, hi):
            if not isinstance(x, (float, int)) or not math.isfinite(x) or not lo <= x <= hi:
                raise ValueError('Invalid numeric project value')
        def ref(key):
            if key and key not in resources:
                raise ValueError('Missing resource reference')
        def title_check(t):
            if not t: return
            ref(t.image)
            if t.background not in {'transparent','solid','gradient','image'}:
                raise ValueError('Invalid background')
            for e in t.elements:
                ref(e.resource)
                for v in (e.x,e.y,e.depth,e.size,e.scale,e.outline,e.shadow_blur): number(v,-10000,10000)
                if e.size<=0 or e.scale<=0: raise ValueError('Size must be positive')
        for s in self.slides:
            number(s.duration,.01,1e12); number(s.transition_duration,0,1e12)
            ref(s.resource); title_check(s.title)
            if s.kind=='video':
                number(s.source_in,0,1e12);number(s.video_gain_db,-120,24)
                number(s.video_fade_in,0,s.duration);number(s.video_fade_out,0,s.duration)
                if s.video_fade_in+s.video_fade_out>s.duration:raise ValueError('Video fades exceed clip duration')
                r=self.resource(s.resource)
                if s.source_in+s.duration>r.info.get('duration',0)+1e-4:raise ValueError('Selected video range exceeds source duration')
        for track in (self.overlays,self.audio1,self.audio2):
            for c in track:
                if c.anchor not in ids: raise ValueError('Missing anchor image')
                ref(c.resource);title_check(c.title)
                for v in (c.fade_in,c.hold,c.fade_out,c.source_in,c.duck_lead,c.duck_release): number(v,0,1e12)
                number(c.offset,-1e12,1e12); number(c.gain_db,-120,24);number(c.duck_db,-60,0)
                if c.duration<=0: raise ValueError('Clip duration must be positive')
        for v in (self.start_fade,self.end_fade,self.default_transition): number(v,0,86400)

    def transition_lengths(self):
        """No triple transitions: each half is bounded to half of the shorter slide."""
        return [min(s.transition_duration, s.duration, self.slides[i+1].duration)
                if s.transition != 'cut' and s.kind!='video' and self.slides[i+1].kind!='video' else 0.
                for i,s in enumerate(self.slides[:-1])]

    def missing(self):
        used=self.used_resources()
        return [(r, attr) for r in self.resources if r.id in used for attr in ('path','right')
                if getattr(r,attr) and not Path(getattr(r,attr)).is_file()]


def save_project(project, path):
    project.validate()
    path = Path(path).resolve()
    data = project.to_dict()
    for r in data['resources']:
        for key in ('path','right'):
            if r[key]:
                try: r[key] = os.path.relpath(r[key],path.parent)
                except ValueError: pass  # Separate Windows drive.
    atomic_json(path, data)


def atomic_json(path, data):
    path = Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp = tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def load_project(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    for r in data.get('resources',[]):
        for key in ('path','right'):
            if r.get(key): r[key] = str((path.parent/r[key]).resolve())
    return Project.from_dict(data)


def backup_project(project, destination):
    """Portable copy, original references unchanged; content hashes avoid name collisions."""
    project.validate()
    data = copy.deepcopy(project.to_dict()); destination = Path(destination)
    fd,tmp = tempfile.mkstemp(prefix='.dido-backup-',suffix='.zip',dir=destination.parent);os.close(fd)
    seen = {}
    try:
        with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
            for r in data['resources']:
                for key in ('path','right'):
                    if not r[key]: continue
                    source=Path(r[key])
                    with source.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
                    if digest not in seen:
                        folder={'audio':'audio','graphic':'graphics'}.get(r['kind'],'images')
                        name=f'{folder}/{digest[:16]}{source.suffix.lower()}'
                        z.write(source,name);seen[digest]=name
                    r[key]=seen[digest]
            z.writestr('DiaDoris.dido',json.dumps(data,ensure_ascii=False,indent=2))
        os.replace(tmp,destination)
    finally:
        Path(tmp).unlink(missing_ok=True)
