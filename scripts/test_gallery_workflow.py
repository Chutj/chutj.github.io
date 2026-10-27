"""Workflow simulations use copies of real FIG material, never the source library."""
import copy
import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import gallery_workflow as workflow
import import_gallery as importer
from public_gallery_schema import APPROVAL_FIELDS, metadata_hash
import test_gallery_import as import_tests
from test_public_gallery import fixture


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.fixture = import_tests.IncrementalGalleryTest()
        self.fixture.setUp()
        self.source = self.fixture.source
        self.root = self.fixture.base/'site'
        self.local = self.root/'.gallery-local'
        self.local.mkdir(parents=True)
        (self.root/'data/gallery').mkdir(parents=True)
        (self.root/'.gitignore').write_text('/.gallery-local/\n__pycache__/\n', encoding='utf-8')
        workflow.save(self.root/'data/gallery/allowlist.json', dict(schema_version=1, image_hosts=['chutj.github.io'], approved_records=[]))
        workflow.save(self.root/'data/gallery/public.json', dict(schema_version=1, records=[]))
        workflow.save(self.root/'data/gallery/media.json', dict(schema_version=1, files=[]))
        workflow.run(['git', 'init', '-b', 'main'], self.root)
        workflow.run(['git', 'config', 'user.name', 'Isolated workflow test'], self.root)
        workflow.run(['git', 'config', 'user.email', 'fixture@example.invalid'], self.root)
        workflow.run(['git', 'add', '.'], self.root)
        workflow.run(['git', 'commit', '-m', 'Isolated fixture baseline'], self.root)
        self.patch_root = patch.object(importer, 'ROOT', self.root)
        self.patch_local = patch.object(importer, 'LOCAL', self.local)
        self.patch_root.start(); self.patch_local.start()
        self.addCleanup(self.patch_root.stop); self.addCleanup(self.patch_local.stop)

    def prepare(self, dry=False):
        return workflow.prepare(self.source, dry, self.root)

    def test_new_image_repeat_and_read_only_dry_run(self):
        before = workflow.observe(self.source)
        self.assertFalse((self.local/'catalog.json').exists())
        self.assertFalse(self.prepare(True)['writes'])
        self.assertFalse((self.local/'catalog.json').exists())
        first = self.prepare()
        self.assertEqual(first['importer']['added'], 2)
        repeat = self.prepare()
        self.assertEqual(first['batch'], repeat['batch'])
        self.assertEqual(repeat['importer']['unchanged'], 2)
        self.assertEqual(repeat['importer']['images_to_copy'], 0)
        self.assertEqual(before, workflow.observe(self.source))
        self.fixture.add_real('散点图', 'NCC_2026_Xu_02762-2_Fig4_g-i.png')
        update = self.prepare()
        self.assertEqual(update['importer']['added'], 1)
        self.assertEqual(update['importer']['valid_records'], 3)
        self.assertNotEqual(first['batch'], update['batch'])

    def test_markdown_change_does_not_duplicate_or_approve(self):
        self.prepare()
        before = {r['id'] for r in workflow.load(self.local/'catalog.json')['records']}
        md = self.source/'地图/地图.md'
        md.write_text(md.read_text(encoding='utf-8')+'\n**Fixture-only update**: review again.\n', encoding='utf-8')
        changed = self.prepare()
        self.assertEqual(changed['importer']['updated'], 1)
        records = workflow.load(self.local/'catalog.json')['records']
        self.assertEqual(before, {r['id'] for r in records})
        self.assertTrue(all(r['rights']['public_use_allowed'] is False for r in records))

    def test_pdf_added_changed_and_cache_reused(self):
        self.prepare()
        registry = workflow.load(importer.DEFAULT_SOURCE/'PDF原文/sources.json')
        entry = next(e for e in registry if e['doi'] == '10.1038/s41467-026-78296-0')
        path = self.source/entry['pdf_relative_path']; path.parent.mkdir(parents=True)
        shutil.copyfile(importer.DEFAULT_SOURCE/entry['pdf_relative_path'], path)
        workflow.save(self.source/'PDF原文/sources.json', [entry])
        before = workflow.observe(self.source)
        first = self.prepare()
        self.assertEqual(first['importer']['pdf_review']['parsed'], 1)
        self.assertEqual(first['importer']['pdf_review']['captions_located'], 1)
        repeat = self.prepare()
        self.assertEqual(repeat['importer']['pdf_review']['parsed'], 0)
        self.assertEqual(repeat['importer']['pdf_review']['reused'], 1)
        self.assertEqual(before, workflow.observe(self.source))
        path.write_bytes(path.read_bytes()+b'\n% Fixture revision\n')
        entry['sha256'] = workflow.digest(path.read_bytes())
        workflow.save(self.source/'PDF原文/sources.json', [entry])
        changed = self.prepare()
        self.assertEqual(changed['importer']['pdf_review']['parsed'], 1)
        self.assertNotEqual(first['batch'], changed['batch'])

    def test_missing_license_is_not_a_ready_proposal(self):
        result = self.prepare()
        self.assertEqual(result['ready'], 0)
        report = workflow.load(self.local/'updates'/result['batch']/'report.json')
        self.assertTrue(all(r['group'] == 'needs-review' for r in report['pending']))
        self.assertEqual(workflow.load(self.root/'data/gallery/allowlist.json')['approved_records'], [])

    def test_manual_english_and_approved_rights_survive_only_unchanged_sources(self):
        self.prepare()
        catalog = workflow.load(self.local/'catalog.json'); source = catalog['records'][0]
        inventory = workflow.load(self.local/'inventory.json')
        raw = next(r for r in inventory['records'] if r['id'] == source['id'])
        public, _ = fixture()
        source.update(title='Reviewed editorial fixture', sections=public['sections'],
                      translation_status='reviewed', rights=public['rights'])
        source['rights']['review_evidence_sha256'] = source['pdf_reference']['evidence_sha256']
        raw['rights'] = copy.deepcopy(source['rights'])
        public = dict(source)
        for field in ('asset', 'colors', 'pdf_reference'):
            public.pop(field, None)
        public.update(source='https://doi.org/'+source['doi'], source_image_sha256=raw['image_sha256'],
            metadata_sha256=metadata_hash(source), image='https://chutj.github.io/figures/approved/fixture.png',
            thumbnail='https://chutj.github.io/figures/approved/fixture.webp', srcset='')
        workflow.save(self.local/'catalog.json', catalog); workflow.save(self.local/'inventory.json', inventory)
        workflow.save(self.root/'data/gallery/allowlist.json', dict(schema_version=1, image_hosts=['chutj.github.io'],
            approved_records=[{k: public[k] for k in APPROVAL_FIELDS}]))
        workflow.save(self.root/'data/gallery/public.json', dict(schema_version=1, records=[public]))
        result = self.prepare()
        self.assertFalse(result['invalidated_public'])
        self.assertIn(source['id'], result['retained_editorial_overlays'])
        self.assertEqual(workflow.load(self.local/'catalog.json')['records'][0]['title'], 'Reviewed editorial fixture')
        md = self.source/raw['canonical_note']
        md.write_text(md.read_text(encoding='utf-8')+'\nChanged fixture evidence.\n', encoding='utf-8')
        result = self.prepare()
        self.assertTrue(result['invalidated_public'])
        self.assertNotIn(source['id'], result['retained_editorial_overlays'])

    def proposal(self):
        source = workflow.load(self.local/'catalog.json')['records'][0]
        raw = next(r for r in workflow.load(self.local/'inventory.json')['records'] if r['id'] == source['id'])
        record, _ = fixture()
        record.update(id=source['id'], width=source['width'], height=source['height'], source_image_sha256=raw['image_sha256'],primary=source['primary'],categories=source['categories'])
        record['metadata_sha256'] = metadata_hash(record)
        record['rights'].update(status='needs-review', human_reviewed=False, public_use_allowed=False)
        evidence = dict(id=source['id'], purpose='Synthetic test only, not an actual permission')
        workflow.save(self.local/'fixture-audit.json', {'records': [evidence]})
        record['rights']['review_evidence_sha256'] = workflow.digest(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode())
        base = 'https://chutj.github.io/figures/approved/'+raw['image_sha256']+'/'
        record.update(image=base+'figure.png', thumbnail=base+'figure-640.webp',
                      srcset=base+'figure-320.webp 320w, '+base+'figure-640.webp 640w')
        return dict(record=record, asset='assets/'+Path(source['asset']).name, evidence_file='fixture-audit.json',
            evidence_id=source['id'], bindings=[dict(id=source['id'], image_sha256=raw['image_sha256'],
                pdf_evidence_sha256=source['pdf_reference']['evidence_sha256'],
                catalog_sha256=workflow.digest(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()),
                inventory_sha256=workflow.digest(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()))])

    def approval(self, result):
        batch = self.local/'updates'/result['batch']
        report = workflow.load(batch/'report.json')
        approval = workflow.load(batch/'approval-template.json')
        approval.update(approved_by='Isolated-policy-test', approved_at='2020-01-01',
            records=[{k: p[k] for k in ('id', 'proposal_sha256')} for p in report['proposals']])
        path = batch/'approval.json'; workflow.save(path, approval)
        return path

    def test_pinned_explicit_approval_dry_plan_and_stale_metadata_rejected(self):
        self.prepare(); proposal = self.proposal()
        workflow.save(self.local/'release-proposals.json', {'records': [proposal]})
        result = self.prepare()
        self.assertEqual(result['ready'], 1)
        path = self.approval(result)
        policy_before = (self.root/'data/gallery/allowlist.json').read_bytes()
        plan = workflow.publish(path, root=self.root)
        self.assertEqual(plan['public_total'], 1)
        self.assertFalse(plan['writes'])
        self.assertEqual(policy_before, (self.root/'data/gallery/allowlist.json').read_bytes())
        self.assertFalse((self.root/'static').exists())
        data = workflow.load(self.local/'catalog.json'); data['records'][0]['title'] += ' changed'
        workflow.save(self.local/'catalog.json', data)
        with self.assertRaisesRegex(ValueError, 'changed since prepare'):
            workflow.publish(path, root=self.root)

    def test_changed_published_image_requires_reapproval(self):
        self.prepare(); entry = workflow.approved_entry(self.proposal(), 'Test-only', '2020-01-01')
        record = entry['record']
        workflow.save(self.local/'publication-records.json', {'records': [entry]})
        workflow.save(self.root/'data/gallery/allowlist.json', dict(schema_version=1, image_hosts=['chutj.github.io'],
            approved_records=[{k: record[k] for k in APPROVAL_FIELDS}]))
        workflow.save(self.root/'data/gallery/public.json', dict(schema_version=1, records=[record]))
        self.assertFalse(self.prepare()['invalidated_public'])
        inventory = workflow.load(self.local/'inventory.json')['records']
        raw = next(r for r in inventory if r['id'] == record['id'])
        path = self.source/raw['source_files'][0]
        # Change every category copy to retain one source identity.
        for relative in raw['source_files']:
            path = self.source/relative; path.write_bytes(path.read_bytes()+b'\n')
        result = self.prepare()
        self.assertEqual(len(result['invalidated_public']), 1)
        self.assertIn('reassessment', result['invalidated_public'][0]['reason'])
        self.assertEqual(workflow.load(self.root/'data/gallery/public.json')['records'], [record])

    def test_removed_source_is_reported_without_deleting_private_bytes(self):
        self.prepare()
        assets = {p.name for p in (self.local/'assets').glob('*')}
        # Only delete the disposable simulation copy, never real FIG.
        shutil.rmtree(self.source/'示意图')
        result = self.prepare()
        self.assertEqual(result['importer']['inactive'], 1)
        self.assertTrue(result['source_changes']['removed'])
        self.assertEqual(assets, {p.name for p in (self.local/'assets').glob('*')})

    def test_publish_executes_gates_and_exact_staging_in_isolated_repository(self):
        self.prepare()
        workflow.save(self.local/'release-proposals.json', {'records': [self.proposal()]})
        result = self.prepare(); approval = self.approval(result)
        real_run = workflow.run
        calls = []
        def command(args, root=workflow.ROOT):
            calls.append(list(args))
            if args[:4] == ['git', 'remote', 'get-url', 'origin']:
                return 'https://github.com/Chutj/chutj.github.io.git'
            if args[:2] == ['git', 'fetch'] or args[:2] == ['git', 'push'] or args[:2] == ['git', 'merge-base']:
                return ''  # Never access the network or a real repository.
            if args[:3] == ['git', 'rev-parse', 'origin/main']:
                return real_run(['git', 'rev-parse', 'HEAD'], root)
            if '-m' in args and 'unittest' in args:
                return 'Tests simulated here; full suite runs separately.'
            return real_run(args, root)
        with patch.object(workflow, 'run', command), \
                patch('check_release_snapshot.check', return_value={'candidate_build': 'passed'}) as build, \
                patch.object(workflow, 'deployment_status', return_value={'runs': [{'conclusion': 'success'}]}):
            published = workflow.publish(approval, execute=True, root=self.root)
        self.assertEqual(published['status'], 'pushed')
        build.assert_called_once()
        self.assertEqual(real_run(['git', 'status', '--short'], self.root), '')
        self.assertEqual(len(workflow.load(self.root/'data/gallery/public.json')['records']), 1)
        self.assertTrue(any(c[:3] == ['git', 'push', 'origin'] for c in calls))
        self.assertFalse(any('--force' in c for c in calls))
        self.assertTrue((self.local/'updates'/result['batch']/'publish-result.json').is_file())

    def test_changed_official_evidence_and_unselected_id_are_rejected(self):
        self.prepare()
        workflow.save(self.local/'release-proposals.json', {'records': [self.proposal()]})
        result = self.prepare(); path = self.approval(result)
        approval = workflow.load(path); approval['records'][0]['id'] = 'not-in-reviewed-batch'
        workflow.save(path, approval)
        with self.assertRaisesRegex(ValueError, 'Unreviewed ID'):
            workflow.publish(path, root=self.root)
        path = self.approval(result)
        workflow.save(self.local/'official-evidence.json', {'fixture': 'new evidence needs refresh'})
        with self.assertRaisesRegex(ValueError, 'review inputs changed'):
            workflow.publish(path, root=self.root)

    def test_credential_candidate_is_blocked(self):
        path = self.root/'scripts/fixture.py'; path.parent.mkdir()
        path.write_text('test_only = "'+'ghp_'+'A'*36+'"', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'credential'):
            workflow.scan_changes(self.root, {'scripts/fixture.py': workflow.digest(path.read_bytes())})

    def test_incomplete_proposal_is_fixable_and_never_approved(self):
        self.prepare(); proposal = self.proposal()
        proposal['record']['metadata_sha256'] = '0'*64
        workflow.save(self.local/'release-proposals.json', {'records': [proposal]})
        result = self.prepare()
        self.assertEqual(result['ready'], 0)
        self.assertEqual(result['pending_groups']['fixable'], 1)
        self.assertEqual(workflow.load(self.root/'data/gallery/allowlist.json')['approved_records'], [])

    def test_nc_selection_requires_actual_use_confirmation(self):
        self.prepare(); proposal = self.proposal()
        proposal['record']['rights'].update(license='CC BY-NC-ND 4.0',
            license_url='https://creativecommons.org/licenses/by-nc-nd/4.0/')
        workflow.save(self.local/'release-proposals.json', {'records': [proposal]})
        result = self.prepare(); path = self.approval(result)
        with self.assertRaisesRegex(ValueError, 'noncommercial'):
            workflow.publish(path, root=self.root)
        approval = workflow.load(path); approval['confirm_noncommercial_use'] = True
        workflow.save(path, approval)
        self.assertFalse(workflow.publish(path, root=self.root)['writes'])

    def test_batch_validation_snapshot_detects_mid_batch_changes(self):
        self.prepare()
        context=workflow.validation_context(self.root)
        workflow.verify_validation_context(self.root,context)
        catalog=workflow.load(self.local/'catalog.json')
        catalog['records'][0]['title']='Changed after validation snapshot'
        workflow.save(self.local/'catalog.json',catalog)
        with self.assertRaisesRegex(ValueError,'changed during batch validation'):
            workflow.verify_validation_context(self.root,context)

    def test_managed_component_blocks_standalone_execute_before_any_public_write(self):
        self.prepare()
        before=(self.root/'data/gallery/allowlist.json').read_bytes()
        (self.root/'gallery-component.lock.json').write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'pinned SCI Figure Gallery component'):
            workflow.publish(self.local/'nonexistent-approval.json',execute=True,root=self.root)
        self.assertEqual((self.root/'data/gallery/allowlist.json').read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
