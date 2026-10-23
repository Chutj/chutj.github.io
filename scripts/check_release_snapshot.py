"""Verify committed HEAD and a Git-tree candidate without private/ignored data.

No commit/push. Any staging/write-tree operations happen in a disposable clone,
never in the website repository's index. All check files remain Git-ignored.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import io
import json
import os
import shutil
import subprocess
import tarfile
import uuid
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parents[1]


def command(args,cwd,env=None,input_text=None):
    run=subprocess.run(args,cwd=cwd,capture_output=True,encoding='utf-8',env=env,input=input_text)
    if run.returncode:
        raise RuntimeError('Command failed: '+' '.join(str(a) for a in args)+'\n'+run.stdout+run.stderr)
    return run.stdout,run.stderr


def check(hugo):
    work=ROOT/'.gallery-local/release-checks'/uuid.uuid4().hex
    work.mkdir(parents=True)
    index=ROOT/command(['git','rev-parse','--git-path','index'],ROOT)[0].strip()
    index_before=index.read_bytes()
    head=command(['git','rev-parse','HEAD'],ROOT)[0].strip()
    command([sys.executable,'-S','scripts/validate_public_gallery.py'],ROOT)
    theme=ROOT/'themes/PaperMod'
    if command(['git','status','--porcelain'],theme)[0].strip():
        raise ValueError('Theme contains uncommitted changes; pin and review it before release checking')
    pin=command(['git','ls-files','--stage','themes/PaperMod'],ROOT)[0].split()[1]
    checkout=work/'committed-checkout'
    command(['git','clone','--no-hardlinks',str(ROOT),str(checkout)],work)
    remote=command(['git','config','--file','.gitmodules','--get','submodule.themes/PaperMod.url'],checkout)[0].strip()
    rewrite='url.'+theme.as_uri()+'.insteadOf='+remote
    command(['git','-c','protocol.file.allow=always','-c',rewrite,'submodule','update','--init','--recursive'],checkout)
    if command(['git','status','--porcelain'],checkout)[0].strip():
        raise ValueError('Committed checkout is not clean')
    if (checkout/'.gallery-local').exists():
        raise ValueError('Private data present in committed checkout')
    env=dict(os.environ,HUGO_ENVIRONMENT='production',HUGO_ENV='production',TZ='Asia/Shanghai',PYTHONNOUSERSITE='1')

    def build(path,name):
        output=work/(name+'-public')
        stdout,stderr=command([hugo,'build','--minify','--noBuildLock','--baseURL','https://chutj.github.io/','--destination',str(output)],path,env)
        if stderr or 'WARN ' in stdout or 'ERROR ' in stdout:
            raise ValueError('Build warnings/errors: '+stdout+stderr)
        return output

    baseline_output=build(checkout,'committed')
    baseline_has_gallery=(baseline_output/'gallery/index.html').is_file()
    # Collect only the exact files Git would consider for the next commit.
    names=command(['git','ls-files','--cached','--others','--exclude-standard','-z'],ROOT)[0].split('\0')
    paths=[]
    for name in sorted(set(filter(None,names))):
        if name=='themes/PaperMod':continue
        path=ROOT/name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Candidate has a deletion/symlink requiring explicit review: '+name)
        if name.startswith(('.gallery-local/','public/','resources/_gen/')):
            raise ValueError('Private candidate file: '+name)
        target=checkout/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
        paths.append(name)
    # This is the disposable clone, not ROOT.
    assert checkout.resolve().is_relative_to(work.resolve())
    command(['git','add','--pathspec-from-file=-','--pathspec-file-nul'],checkout,
        input_text='\0'.join(paths)+'\0')
    changes=command(['git','diff','--cached','--name-status','HEAD'],checkout)[0].splitlines()
    tree=command(['git','write-tree'],checkout)[0].strip()
    archived=subprocess.check_output(['git','archive','--format=tar',tree],cwd=checkout)
    candidate=work/'candidate-snapshot'
    candidate.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
        for member in archive.getmembers():
            relative=PurePosixPath(member.name)
            if relative.is_absolute() or '..' in relative.parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe Git archive entry')
            destination=candidate.joinpath(*relative.parts)
            if member.isdir():destination.mkdir(parents=True,exist_ok=True)
            else:
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(archive.extractfile(member).read())
    # Retain a real Git index/history for validation and Hugo GitInfo if needed.
    shutil.copytree(checkout/'.git',candidate/'.git')
    target_theme=candidate/'themes/PaperMod'
    command(['git','clone','--no-hardlinks',str(theme),str(target_theme)],candidate)
    command(['git','checkout','--detach',pin],target_theme)
    if (candidate/'.gallery-local').exists():
        raise ValueError('Private data leaked into candidate snapshot')
    # The public validator accepts only exact, explicitly approved media hashes.
    # All other raster source/output files continue to fail closed.
    command([sys.executable,'-S','scripts/validate_public_gallery.py'],candidate,env)
    candidate_output=build(candidate,'candidate')
    command([sys.executable,'-S','scripts/validate_public_gallery.py','--output',str(candidate_output)],candidate,env)
    dataset=json.loads((candidate/'data/gallery/public.json').read_text(encoding='utf-8'))
    gallery=(candidate_output/'gallery/index.html').read_text(encoding='utf-8')
    if not dataset['records']:
        if 'No public figures available' not in gallery or 'gallery-data' in gallery:
            raise ValueError('Empty public Gallery did not degrade safely')
    policy=json.loads((candidate/'data/gallery/allowlist.json').read_text(encoding='utf-8'))
    approved={r['id'] for r in policy['approved_records']}
    private=ROOT/'.gallery-local/catalog.json'
    if private.exists():
        denied=[r['id'] for r in json.loads(private.read_text(encoding='utf-8'))['records'] if r['id'] not in approved]
        for path in candidate_output.rglob('*'):
            if path.is_file() and path.suffix in ('.html','.json','.xml','.js'):
                text=path.read_text(encoding='utf-8')
                if any(uid in text for uid in denied):
                    raise ValueError('Unauthorized private ID in candidate publish output')
    if index.read_bytes()!=index_before or command(['git','rev-parse','HEAD'],ROOT)[0].strip()!=head:
        raise ValueError('Source Git index/HEAD changed unexpectedly')
    report=dict(head=head,theme_pin=pin,committed_build='passed',committed_has_gallery=baseline_has_gallery,
        candidate_tree=tree,candidate_build='passed',private_directory_in_candidate=False,
        public_figures=len(dataset['records']),candidate_changes=changes,
        source_index_unchanged=True,source_head_unchanged=True,
        note='Filesystem/standard-library CI simulation on Windows; hosted Linux Actions not executed.',
        output=str(candidate_output),candidate_source=str(candidate))
    (work/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    print('Report: '+str(work/'report.json'))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hugo',default=shutil.which('hugo') or str(Path.home()/'AppData/Local/Microsoft/WinGet/Packages/Hugo.Hugo.Extended_Microsoft.Winget.Source_8wekyb3d8bbwe/hugo.exe'))
    args=parser.parse_args()
    try:check(args.hugo)
    except (ValueError,OSError,RuntimeError,subprocess.CalledProcessError) as exc:
        print('STOP: '+str(exc),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
