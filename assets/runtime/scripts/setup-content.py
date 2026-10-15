"""Install content-reading dependencies into this deployment's own environment."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-media',action='store_true',help='Also install local audio/video transcription and download its model')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    runtime=root/'.runtime';temporary=runtime/'tmp';temporary.mkdir(parents=True,exist_ok=True)
    python=root/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')
    if not python.exists():venv.EnvBuilder(with_pip=True).create(root/'.venv')
    environment={**os.environ,'TEMP':str(temporary),'TMP':str(temporary),'TMPDIR':str(temporary),
                 'PYTHONUTF8':'1','PLAYWRIGHT_BROWSERS_PATH':str(runtime/'browsers'),
                 'HF_HOME':str(runtime/'huggingface'),'HF_HUB_DISABLE_TELEMETRY':'1','HF_HUB_DISABLE_XET':'1'}
    def run(*argv):subprocess.run([str(python),*argv],cwd=root,env=environment,check=True)
    run('-m','pip','install','-r',str(root/'scripts/requirements-content.txt'))
    candidates=[Path(os.environ.get(key,''))/'Google/Chrome/Application/chrome.exe' for key in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA') if os.environ.get(key)]
    if not any(path.is_file() for path in candidates):run('-m','playwright','install','chromium')
    if args.with_media:
        run('-m','pip','install','-r',str(root/'scripts/requirements-voice.lock.txt'))
        run(str(root/'scripts/transcribe.py'),'--model-dir',str(runtime/'models/base'),'--download')
    print('Content reader installed in this deployment. No accounts bound or services started.')


if __name__=='__main__':main()
