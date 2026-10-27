"""Record exact saved image identities without conflating config/manifest/index."""
import argparse,hashlib,json,os,subprocess,tarfile
from pathlib import Path
SOURCE='18b9477692b0637a0120a8358e938346b811fbae'
TREE='54d17f98bd8d57e109275e32f01bda1144a5dff8'
def digest(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def inspect_archive(path,image):
 with tarfile.open(path) as t:
  members=t.getmembers();names=[m.name for m in members];assert len(names)==len(set(names))
  assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in names)
  save=json.load(t.extractfile('manifest.json'));assert len(save)==1
  raw=t.extractfile(save[0]['Config']).read();cfg=json.loads(raw);config_digest='sha256:'+hashlib.sha256(raw).hexdigest()
  assert cfg['architecture']=='amd64' and cfg['os']=='linux'
  assert cfg['config']['Labels']['org.opencontainers.image.revision']==SOURCE
  assert cfg['config']['Labels']['org.opencontainers.image.source']=='https://github.com/meser-recovery/starter-package'
  nodes=[]
  for m in members:
   if not m.isfile() or not m.name.startswith('blobs/sha256/'):continue
   h=hashlib.sha256();small=bytearray()
   with t.extractfile(m) as f:
    for b in iter(lambda:f.read(1048576),b''):
     h.update(b)
     if m.size<1048576:small.extend(b)
   assert h.hexdigest()==m.name.rsplit('/',1)[-1]
   if not small:continue
   try:v=json.loads(small)
   except (ValueError,UnicodeDecodeError):continue
   if isinstance(v,dict) and ('manifests' in v or 'layers' in v):nodes.append({'digest':'sha256:'+h.hexdigest(),'kind':'index' if 'manifests' in v else 'manifest','media_type':v.get('mediaType'),'config_digest':v.get('config',{}).get('digest')})
  kind=next((x['kind'] for x in nodes if x['digest']==image['Id']),None)
  if kind is None and image['Id']==config_digest:kind='config'
  assert kind is not None
  assert image['Architecture']=='amd64' and image['Os']=='linux'
  assert image['Config']['Labels']['org.opencontainers.image.revision']==SOURCE
  return {'source':SOURCE,'tree':TREE,'platform':'linux/amd64','engine_image_id':image['Id'],'engine_representation':kind,'config_digest':config_digest,'oci_objects':nodes,'revision_labels':{k:v for k,v in cfg['config']['Labels'].items() if k.startswith('org.opencontainers.image.')},'archive':path.name,'archive_sha256':digest(path),'archive_bytes':path.stat().st_size}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args()
 assert subprocess.check_output(['git','-C',str(a.source),'rev-parse','HEAD']).decode().strip()==SOURCE
 assert subprocess.check_output(['git','-C',str(a.source),'rev-parse','HEAD^{tree}']).decode().strip()==TREE
 assert not subprocess.check_output(['git','-C',str(a.source),'status','--porcelain'])
 components={}
 for role,tag,name in [('gateway','meser-service-gateway:','gateway-image.tar'),('frontend','meser-service-caddy:','caddy-frontend-image.tar')]:
  image=json.loads(subprocess.check_output(['docker','image','inspect',tag+SOURCE]))[0];components[role]=inspect_archive(a.output/name,image);components[role]['image_tag']=tag+SOURCE
 manifest={'schema':1,'status':'EXACT_GITHUB_ACTIONS_BUILD','source_sha':SOURCE,'source_tree':TREE,'components':components,'build_provenance':{'repository':os.environ.get('GITHUB_REPOSITORY'),'run_id':os.environ.get('GITHUB_RUN_ID'),'run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),'workflow_ref':os.environ.get('GITHUB_WORKFLOW_REF'),'workflow_sha':os.environ.get('GITHUB_WORKFLOW_SHA'),'control_checkout_sha':os.environ.get('GITHUB_SHA'),'runner_os':os.environ.get('RUNNER_OS'),'runner_arch':os.environ.get('RUNNER_ARCH')},'files':{p.name:{'sha256':digest(p),'bytes':p.stat().st_size} for p in sorted(a.output.iterdir()) if p.is_file() and p.name not in ('release-manifest.json','SHA256SUMS')},'vmhome_upload':'NOT_RUN','identity_rules':'config_digest, platform manifest digest and index digest identify different OCI objects; engine_image_id kind recorded explicitly'}
 (a.output/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 (a.output/'SHA256SUMS').write_text(''.join(digest(p)+'  '+p.name+'\n' for p in sorted(a.output.iterdir()) if p.is_file() and p.name!='SHA256SUMS'))
 print(json.dumps({'source':SOURCE,'tree':TREE,'components':components},indent=2))
if __name__=='__main__':main()
