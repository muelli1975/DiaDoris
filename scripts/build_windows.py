"""Build a portable test package. Publication is deliberately separate."""
from pathlib import Path
import hashlib
import importlib.metadata
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from diadoris import __version__


def main():
    subprocess.run([sys.executable,str(ROOT/'scripts/create_demo.py')],check=True)
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir','--name','DiaDoris',
          '--contents-directory','.','--collect-all','pillow_heif','--hidden-import','transcora.core.bd3d_export',
          '--hidden-import','diadoris.video','--add-data',str(ROOT/'presets')+':presets',
          '--add-data',str(ROOT/'reference')+':reference',str(ROOT/'run_diadoris.py')]
    subprocess.run(args,cwd=ROOT,check=True)
    folder=ROOT/'dist/DiaDoris'
    shutil.copytree(ROOT/'tools',folder/'tools',dirs_exist_ok=True)
    shutil.copytree(ROOT/'examples',folder/'examples',dirs_exist_ok=True)
    for name in ('README.md','README_DE.md','LICENSE','THIRD_PARTY.md'):shutil.copy2(ROOT/name,folder/name)
    source=folder/'source';source.mkdir(exist_ok=True)
    for name in ('diadoris','transcora','presets','scripts','tests','reference','.github'):
        shutil.copytree(ROOT/name,source/name,ignore=shutil.ignore_patterns('__pycache__'),dirs_exist_ok=True)
    for name in ('run_diadoris.py','requirements.txt','requirements-build.txt','README.md','README_DE.md','LICENSE','THIRD_PARTY.md'):shutil.copy2(ROOT/name,source/name)
    licenses=folder/'licenses';licenses.mkdir(exist_ok=True)
    for name in ('PySide6','PySide6_Essentials','PySide6_Addons','shiboken6','Pillow','numpy','pillow-heif'):
        try:
            dist=importlib.metadata.distribution(name)
            for file in dist.files or []:
                if '.dist-info/licenses/' in str(file).lower():
                    out=licenses/name/Path(str(file).split('/licenses/',1)[-1]);out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dist.locate_file(file),out)
        except importlib.metadata.PackageNotFoundError:pass
    path=ROOT/'dist'/f'DiaDoris_{__version__}_Test_Windows_x64.zip'
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for file in folder.rglob('*'):
            if file.is_file():z.write(file,Path('DiaDoris')/file.relative_to(folder))
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    path.with_suffix(path.suffix+'.sha256').write_text(f'{digest}  {path.name}\n',encoding='utf-8')
    print(path)


if __name__=='__main__':main()
