"""Reconstruction, update identity and fail-closed upstream conflict tests."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import materialize
import prepare


class PipelineTests(unittest.TestCase):
    def test_identity_tracks_both_inputs_and_keeps_legacy_tag_shape(self):
        first=prepare.identity('a'*40,'b'*40)
        self.assertRegex(first,r'^[a-f0-9]{40}$')
        self.assertEqual(first,prepare.identity('a'*40,'b'*40))
        self.assertNotEqual(first,prepare.identity('a'*40,'c'*40))
        self.assertNotEqual(first,prepare.identity('d'*40,'b'*40))
        with self.assertRaises(ValueError):prepare.identity('main','b'*40)

    def test_skip_requires_a_complete_published_release(self):
        names=['ctr-nitrofueled-1-1-x86_64.pkg.tar.zst','PKGBUILD','SRCINFO','install.sh','SHA256SUMS','upstream.json']
        release={'isDraft':False,'assets':[{'name':name} for name in names]}
        self.assertTrue(prepare.complete(release))
        release['isDraft']=True
        self.assertFalse(prepare.complete(release))
        release['isDraft']=False
        release['isPrerelease']=True
        self.assertFalse(prepare.complete(release))
        release['isPrerelease']=False
        release['assets'].pop()
        self.assertFalse(prepare.complete(release))

    def test_upstream_fix_combines_with_native_patch(self):self.exercise(False)
    def test_upstream_conflict_preserves_source_head(self):self.exercise(True)

    def exercise(self,conflict):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            def git(*args):return subprocess.check_output(['git','-C',str(source),*args],text=True,stderr=subprocess.STDOUT).strip()
            git('init','-b','main');git('config','user.name','Test');git('config','user.email','test@example.invalid')
            (source/'feature.c').write_text('base\n')
            (source/'fix.c').write_text('original\n')
            git('add','.');git('commit','-m','base');base=git('rev-parse','HEAD')
            (source/'feature.c').write_text('native\n')
            patch=git('diff','--full-index')+'\n'
            git('reset','--hard','HEAD')
            (source/('feature.c' if conflict else 'fix.c')).write_text('upstream\n')
            git('add','.');git('commit','-m','upstream');head=git('rev-parse','HEAD')
            policy=root/'policy';helpers=policy/'.github/workflows/ctr'
            for name in ('patches','arch','docs','assets'):(helpers/name).mkdir(parents=True)
            (helpers/'patches/0001.patch').write_text(patch)
            (helpers/'upstream.json').write_text(json.dumps({'patch_base':base,'repository':str(source)}))
            (helpers/'test_arch_packaging.py').write_text('# fixture\n')
            (helpers/'arch/PKGBUILD').write_text('# native recipe\n')
            (source/'tests').mkdir();(source/'packaging').mkdir();(source/'docs').mkdir()
            for name in ('FEATURES.md','CUSA14876.md','UPSTREAM.md'):(helpers/'docs'/name).write_text(name)
            (policy/'README.md').write_text('native screenshot preserved\n')
            # Track empty fixtures so clean-source verification has no unrelated files.
            if conflict:
                with self.assertRaisesRegex(RuntimeError,'conflict'):materialize.apply(source,policy)
                self.assertEqual(git('rev-parse','HEAD'),head)
                self.assertEqual(git('status','--porcelain'),'')
                self.assertEqual((source/'feature.c').read_text(),'upstream\n')
            else:
                materialize.apply(source,policy)
                self.assertEqual((source/'feature.c').read_text(),'native\n')
                self.assertEqual((source/'fix.c').read_text(),'upstream\n')
                self.assertEqual((source/'README.md').read_text(),'native screenshot preserved\n')
                self.assertEqual((source/'packaging/arch/PKGBUILD').read_text(),'# native recipe\n')
                with self.assertRaisesRegex(ValueError,'clean'):materialize.apply(source,policy)


if __name__=='__main__':unittest.main()
