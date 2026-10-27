"""Read-only PDF evidence enrichment of the existing private FIG catalog.

PyMuPDF is imported lazily: it is never required by the public build. Evidence,
quotes, paths and drafts remain under .gallery-local; nothing here grants rights.
"""
import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

sys.dont_write_bytecode = True
VERSION = 2
CAPTION_PARSER_VERSION = 2
LICENSE_PARSER_VERSION = 3
DOI = re.compile(r'10\.\d{4,9}/[-._;/:A-Za-z0-9]+', re.I)
CAPTION = re.compile(r'^\s*(Fig(?:ure)?\.?\s*(\d+))\s*(?:[|:]|\.(?=\s))', re.I)
BARE_CAPTION = re.compile(r'^(Fig(?:ure)?\.?\s*(\d+))\s+[A-Z][^.]{8,220}\.(?:\s*[a-z](?:,\s*[a-z])?)?$')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode('utf-8')


def clean(text):
    text = text.replace('\u00ad', '').replace('ﬁ', 'fi').replace('ﬂ', 'fl')
    return re.sub(r'\s+', ' ', re.sub(r'(\w)-\n(\w)', r'\1\2', text)).strip()


def current_note_evidence(source, raw, note_cache=None):
    """Observe current selected Markdown blocks even in PDF-only refresh mode.

    Keep the imported Chinese snapshot intact; new evidence is additional data.
    A missing or ambiguous block is explicit, never substituted with another note.
    """
    result=[]
    for variant in raw.get('variants',[]):
        relative=variant.get('path','').replace('\\','/')
        path=(source/relative).resolve()
        item=dict(path=relative,status='missing-or-unsafe')
        if path.is_relative_to(source.resolve()) and path.is_file():
            if note_cache is None:
                note_cache = {}
            if path not in note_cache:
                text=path.read_text(encoding='utf-8-sig')
                note_cache[path] = (text, [(b, unquote(b)) for b in re.split(r'(?m)^##\s+',text)[1:]])
            text, indexed_blocks = note_cache[path]
            blocks=[b for b, decoded in indexed_blocks
                    if variant.get('filename') and variant['filename'] in decoded]
            item['status']='matched' if len(blocks)==1 else 'ambiguous-or-missing-block'
            item['sha256']=digest(blocks[0].encode('utf-8')) if len(blocks)==1 else digest(text.encode('utf-8'))
        result.append(item)
    return result


def load(path, default):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def license_candidate(pages):
    """Separate an article's explicit grant from licenses mentioned for datasets."""
    evidence, found, article_found = [], set(), set()
    for number, page in enumerate(pages, 1):
        for block in page['blocks']:
            text = clean(block['text']); low = text.lower()
            compact = re.sub(r'[\s-]+', '', low)
            if re.search(r'creative\s*commons|exclusive licen[cs]e|all rights reserved|copyright|©', low):
                evidence.append(dict(page=number, bbox=block['bbox'], text=text))
            local = set()
            if 'creativecommons' in compact and ('4.0' in compact):
                nc = 'noncommercial' in compact
                if 'noderivative' in compact:
                    local.add('CC BY-NC-ND 4.0' if nc else 'CC BY-ND 4.0')
                elif 'sharealike' in compact:
                    local.add('CC BY-NC-SA 4.0' if nc else 'CC BY-SA 4.0')
                elif nc:
                    local.add('CC BY-NC 4.0')
                elif 'attribution' in compact:
                    local.add('CC BY 4.0')
            if re.search(r'exclusive licen[cs]e(?!e\b)|all rights reserved', low):
                local.add('Publisher exclusive license / permission required')
            found.update(local)
            if re.search(r'this\s+(?:is\s+an?\s+open.access\s+article|article\s+(?:is\s+)?(?:licensed|distributed|published))',low) or ('copyright' in low and 'distributed under' in low and 'creativecommons' in compact):
                article_found.update(local)
        text = clean(' '.join(b['text'] for b in page['blocks']))
        if 'creative' in text.lower() and 'commons' in text.lower():
            for url in page['links']:
                match = re.search(r'creativecommons.org/licenses/(by(?:-nc)?(?:-nd|-sa)?)/4.0', url, re.I)
                if match:
                    found.add('CC '+match[1].upper()+' 4.0')
                    evidence.append(dict(page=number,url=url,text='License hyperlink on PDF page; verify the nearby article notice.'))
    selected = article_found or found
    return dict(candidate=next(iter(selected)) if len(selected)==1 else 'unverified',
                detected=sorted(selected), evidence=evidence, conflict=len(selected)>1)


def caption_label(block):
    text = clean(block['text'])
    match = CAPTION.match(text)
    if match:
        return match, 2 if re.search(r'[|:]$', match[0]) else 0
    # Older publisher captions have no separator. Require a short, distinct
    # title font run ending in a period; a bare body reference is insufficient.
    if block.get('caption_heading'):
        match = BARE_CAPTION.match(block['caption_heading'])
        if match:
            return match, 1
    return None, -1


def extract_captions(pages):
    captions = {}
    strengths = {}
    for page_number, page in enumerate(pages, 1):
        for block in page['blocks']:
            match, strength = caption_label(block)
            if not match:
                continue
            bbox = block['bbox']
            continuation = [b for b in page['blocks'] if b is not block
                and b['bbox'][0] > bbox[2] and abs(b['size']-block['size']) < .7
                and b['bbox'][1] < bbox[3] and b['bbox'][3] > bbox[1]
                and caption_label(b)[0] is None]
            selected = [block]+sorted(continuation, key=lambda b: b['bbox'][1])
            text = clean('\n'.join(b['text'] for b in selected))
            number = match[2]
            if strength > strengths.get(number, -1):
                captions[number] = []
                strengths[number] = strength
            if strength == strengths[number]:
                captions[number].append(dict(page=page_number, figure='Figure '+number,
                    bbox=[b['bbox'] for b in selected], text=text,
                    sha256=digest(text.encode()), extraction_status='candidate-needs-visual-check'))
    return captions


def extract_pdf(path, content):
    import fitz
    with fitz.open(stream=content, filetype='pdf') as doc:
        if doc.needs_pass:
            raise ValueError('Encrypted PDF requires a password; not parsed')
        pages = []
        for page in doc:
            blocks = []
            for block in page.get_text('dict')['blocks']:
                if 'lines' not in block:
                    continue
                spans = [s for line in block['lines'] for s in line['spans']]
                text = '\n'.join(''.join(s['text'] for s in line['spans']) for line in block['lines'])
                runs = []
                for span in spans:
                    font = span['font'].split('+')[0]
                    if not runs or runs[-1][0] != font:
                        runs.append([font, span['text']])
                    else:
                        runs[-1][1] += span['text']
                heading = clean(runs[0][1]) if len(runs) > 1 else ''
                blocks.append(dict(text=text, bbox=[round(x,2) for x in block['bbox']],
                    size=round(sum(s['size'] for s in spans)/max(1,len(spans)),2),
                    caption_heading=heading if BARE_CAPTION.fullmatch(heading) else ''))
            pages.append(dict(blocks=blocks, links=[l['uri'] for l in page.get_links() if l.get('uri')]))
        head = ' '.join(b['text'] for p in pages[:2] for b in p['blocks'])
        identifiers = sorted({m[0].lower().rstrip('.,;)') for m in DOI.finditer(head)})
        return dict(parser_version=VERSION, caption_parser_version=CAPTION_PARSER_VERSION,
                    license_parser_version=LICENSE_PARSER_VERSION,
                    sha256=digest(content), pages=pages,
                    dois=identifiers, document_dois=document_identifiers(pages), title_text=clean(head), captions=extract_captions(pages),
                    article_license=license_candidate(pages))


def registered_pdf_match(doi, name, pdf, entry, expected):
    if doi in pdf['dois'] and (name == expected or pdf['sha256'] == entry.get('sha256')):
        return True
    # Some journal PDFs print the DOI only on the final page. Require BOTH the
    # exact registered path and bytes, then the DOI in this document. The build
    # separately cross-checks the title; a reference-list DOI alone is not enough.
    return (name == expected and pdf['sha256'] == entry.get('sha256')
            and doi in pdf.get('document_dois', []))


def document_identifiers(pages):
    text = ' '.join(b['text'] for p in pages for b in p['blocks'])
    text += ' ' + ' '.join(url for p in pages for url in p['links'])
    return sorted({m[0].lower().rstrip('.,;)') for m in DOI.finditer(text)})


def discover(source, output):
    """Index DOI registry plus content identity; never trust absolute registry paths."""
    directory = source/'PDF原文'
    registry = load(directory/'sources.json', [])
    diagnostics, parsed, writes = [], {}, {}
    stats = dict(pdfs_found=0, parsed=0, reused=0)
    if not directory.is_dir():
        return {}, writes, [dict(code='pdf_directory_missing', detail='PDF原文/')], stats
    if not isinstance(registry,list):
        raise ValueError('PDF sources.json must be a list')
    for path in sorted(directory.rglob('*.pdf')):
        if not path.resolve().is_relative_to(source.resolve()):
            diagnostics.append(dict(code='pdf_outside_source',detail=str(path)))
            continue
        stats['pdfs_found'] += 1
        content = path.read_bytes(); checksum = digest(content)
        cache_path = output/'pdf-cache'/f'{checksum}-v{VERSION}.json'
        try:
            cached = load(cache_path,{})
            if (cached.get('sha256') == checksum and cached.get('parser_version') == VERSION
                    and cached.get('caption_parser_version') == CAPTION_PARSER_VERSION):
                upgraded = False
                if cached.get('license_parser_version') != LICENSE_PARSER_VERSION:
                    cached['article_license'] = license_candidate(cached['pages'])
                    cached['license_parser_version'] = LICENSE_PARSER_VERSION
                    upgraded = True
                if 'document_dois' not in cached:
                    cached['document_dois'] = document_identifiers(cached['pages'])
                    upgraded = True
                if upgraded:
                    writes[cache_path] = encoded(cached)
                parsed_pdf = cached; stats['reused'] += 1
            else:
                parsed_pdf = extract_pdf(path,content); stats['parsed'] += 1
                writes[cache_path] = encoded(parsed_pdf)
            parsed[path.relative_to(source).as_posix()] = parsed_pdf
        except (ValueError,RuntimeError,OSError) as exc:
            diagnostics.append(dict(code='pdf_parse_failed',detail=str(path),error=str(exc)))
    matches = {}
    for entry in registry:
        if not isinstance(entry,dict) or not DOI.fullmatch(entry.get('doi','')):
            diagnostics.append(dict(code='invalid_pdf_registry_entry',detail=str(entry)))
            continue
        doi = entry['doi'].lower()
        expected = (entry.get('pdf_relative_path') or '').replace('\\','/')
        expected_path = source/expected
        if not expected or not expected_path.resolve().is_relative_to(source.resolve()):
            diagnostics.append(dict(code='invalid_pdf_registry_path',detail=doi))
            continue
        options = [(name,p) for name,p in parsed.items()
            if registered_pdf_match(doi,name,p,entry,expected)]
        # New PDF versions with changed hashes can match a registry DOI + title,
        # but multiple different contents remain ambiguous rather than auto-chosen.
        if not options:
            words=set(re.findall(r'[a-z]{3,}',entry.get('title','').lower()))
            options=[(name,p) for name,p in parsed.items() if doi in p['dois'] and words
                and len(words & set(re.findall(r'[a-z]{3,}',p['title_text'].lower())))/len(words)>.8]
        if len({p['sha256'] for _,p in options}) != 1:
            diagnostics.append(dict(code='pdf_missing_or_ambiguous',detail=doi))
            continue
        name,pdf = sorted(options)[0]
        if doi in matches:
            diagnostics.append(dict(code='duplicate_pdf_registry_doi',detail=doi)); matches[doi]=None
            continue
        mismatches=[]
        if name != expected: mismatches.append('Registry path differs; matched by SHA256 and in-document DOI.')
        if pdf['sha256'] != entry.get('sha256'): mismatches.append('PDF differs from registry checksum; re-review version.')
        matches[doi]=dict(registry=entry,path=name,pdf=pdf,issues=mismatches)
    # Unregistered PDFs can be linked only with a unique publisher DOI in the
    # first two pages. The record's title is cross-checked below as well.
    for name,pdf in parsed.items():
        if len(pdf['dois'])==1 and pdf['dois'][0] not in matches:
            doi=pdf['dois'][0]
            same=[p for p in parsed.values() if doi in p['dois']]
            if len({p['sha256'] for p in same})==1:
                matches[doi]=dict(registry={},path=name,pdf=pdf,issues=['PDF absent from source registry; DOI/title match needs review.'])
    return matches,writes,diagnostics,stats


def build(source, output, catalog, inventory, state):
    """Return an immutable plan; dry-run can use it without writing a cache."""
    matches,writes,diagnostics,stats = discover(source,output)
    candidates=load(output/'english-candidates.json',{})
    official=load(output/'official-evidence.json',{})
    old_review=load(output/'pdf-review.json',{}).get('figures',{})
    papers,figures={},{}
    note_cache={}
    catalog=copy.deepcopy(catalog); inventory=copy.deepcopy(inventory); state=copy.deepcopy(state)
    raw_by_id={r['id']:r for r in inventory['records']}
    for record in catalog['records']:
        uid,doi=record['id'],record['doi'].lower()
        raw=raw_by_id[uid]; match=matches.get(doi)
        reference=dict(status='unverified',pdf=None,caption=None,body_references=[])
        article_license=dict(candidate='unverified',evidence=[],detected=[],conflict=False)
        unresolved=[]; paper_id=doi; pdf_hash=None
        if match:
            pdf=match['pdf']; pdf_hash=pdf['sha256']
            words=set(re.findall(r'[a-z]{3,}',record['paper'].lower()))
            title_match=bool(words) and len(words & set(re.findall(r'[a-z]{3,}',pdf['title_text'].lower())))/len(words)>.8
            if not title_match:
                unresolved.append('DOI matched but title cross-check failed; PDF not associated.')
                match=None
        if match:
            paper_id=match['registry'].get('paper_id',doi)
            article_license=match['pdf']['article_license']
            unresolved.extend(match['issues'])
            reference.update(pdf=match['path'],pdf_sha256=pdf_hash,status='paper-matched')
            number=re.search(r'\bFig(?:ure)?\.?\s*(\d+)',record['figure'],re.I)
            options=match['pdf']['captions'].get(number[1],[]) if number else []
            if len(options)==1:
                reference['caption']=options[0]; reference['status']='caption-located'
                unresolved.append('Figure-level caption located; crop/panel correspondence and full caption extraction require human visual review.')
                for p,page in enumerate(match['pdf']['pages'],1):
                    for block in page['blocks']:
                        text=clean(block['text'])
                        if not CAPTION.match(text) and re.search(r'\bFig(?:ure)?s?\.?\s*'+number[1]+r'\b',text,re.I):
                            reference['body_references'].append(dict(page=p,bbox=block['bbox'],text=text))
                reference['body_references']=reference['body_references'][:12]
            else:
                unresolved.append('Caption missing or ambiguous; do not substitute another figure.')
        else:
            unresolved.append('No reliable DOI/title PDF association; PDF evidence pending.')
        caption=reference.get('caption') or {}
        credit=[e for e in [caption] if re.search(r'©|copyright|reproduced|adapted from|with permission|courtesy|credit:|basemap|natural\s*earth|biorender|CC BY',e.get('text',''),re.I)]
        status='restricted' if 'exclusive' in article_license['candidate'].lower() else ('needs-review' if article_license['candidate']!='unverified' or caption else 'unverified')
        if article_license.get('conflict'): unresolved.append('Conflicting article license signals; resolve before any use.')
        official_license=official.get(doi,{}).get('article_license','unverified')
        if official_license!='unverified' and official_license!=article_license['candidate']:
            unresolved.append('Official page and PDF license candidates disagree; resolve version and license before publication.')
            status='needs-review'
        unresolved.append('No automatic permission: check all caption/credit lines, website purpose, image crop, download and adaptation scope.')
        if 'ND' in article_license['candidate']:
            unresolved.append('NoDerivatives: determine whether the existing selected-panel crop is adapted material. Technical resizing alone is not automatically an adaptation.')
        if 'NC' in article_license['candidate']:
            unresolved.append('NonCommercial: confirm the intended site/use is eligible; academic context alone is insufficient.')
        note_hashes=[v.get('note_sha256') for v in raw.get('variants',[])]
        current_notes=current_note_evidence(source,raw,note_cache)
        raw['current_note_evidence']=current_notes
        if any(n['status']!='matched' for n in current_notes):
            unresolved.append('Current source Markdown block missing or ambiguous; compare the retained imported notes before review.')
        fingerprint=digest(encoded(dict(version=VERSION,pdf=pdf_hash,caption=caption.get('sha256'),
            license=article_license,image=raw['image_sha256'],notes=note_hashes,current_notes=current_notes,
            official=official.get(doi),figure=record['figure'])))
        candidate=candidates.get(uid,{})
        if not candidate and caption and record['translation_status']!='reviewed':
            # A deterministic extraction scaffold for future records, not an
            # invented scholarly interpretation or a reviewed translation.
            topic=caption['text'].split('|',1)[-1].split('. ')[0][:240]
            candidate=dict(status='candidate-needs-review',generation='extraction-only',
                evidence_sha256=fingerprint,title=record['title'],sections={
                    'What the figure shows':'Caption topic (source extract; paraphrase and verify the selected panels): '+topic,
                    'Verification & limitations':'Automatically extracted evidence scaffold. A scientific English summary and panel-specific checks are still required.'})
        valid_candidate=(caption and candidate.get('evidence_sha256')==fingerprint
                         and candidate.get('status')=='candidate-needs-review'
                         and not re.search(r'[\u3400-\u9fff]',json.dumps(
                             {k:candidate.get(k) for k in ('title','sections')},ensure_ascii=False)))
        if candidate and not valid_candidate: unresolved.append('English candidate evidence changed or candidate invalid; withheld pending revision.')
        changed=old_review.get(uid,{}).get('evidence_sha256')!=fingerprint
        if changed:
            # Conservative even on first PDF association; no prior permission is
            # carried forward against a newly discovered source/version/license.
            reset=dict(status='unverified',public_use_allowed=False,human_reviewed=False,
                license=None,license_url=None,attribution=None,evidence=None,
                approved_by=None,approved_at=None,review_evidence_sha256=None)
            record['rights']=copy.deepcopy(reset);raw['rights']=copy.deepcopy(reset)
            if uid in state['records']:state['records'][uid]['rights']=copy.deepcopy(reset)
        local_summary=dict(status=reference['status'],pdf_label=Path(reference['pdf']).name if reference['pdf'] else None,
            page=caption.get('page'),figure=caption.get('figure'),article_license=article_license['candidate'],
            review_status=status,evidence_sha256=fingerprint,
            candidate=candidate.get('sections',{}) if valid_candidate else {},
            candidate_title=candidate.get('title') if valid_candidate else None)
        # Do not serialize raw captions, original PDF paths or body quotes to HTML.
        record['pdf_reference']=local_summary
        raw['pdf_reference']=dict(local_summary,source=reference)
        if uid in state['records']:state['records'][uid]['pdf_evidence_sha256']=fingerprint
        figure=dict(id=uid,doi=doi,paper_id=paper_id,journal=record['journal'],year=record['year'],
            figure_id=record['figure'],pdf_source=reference.get('pdf'),reference=reference,
            article_license=article_license,figure_specific_rights=dict(candidate_credit_lines=credit,
                status='credit-lines-not-cleared',note='No detected exception is not proof of no third-party rights.'),
            evidence_source=official.get(doi),evidence_sha256=fingerprint,
            attribution_requirements='Verify creator(s), title/source DOI, copyright notice, exact license link and changes; retain existing credit lines.',
            review_status=status,human_reviewed=False,public_use_allowed=False,
            unresolved_issues=unresolved,
            recommended_action='Review this figure against the rendered PDF and the official article permission page; obtain permission if applicable.',
            rights_holder='See PDF copyright notice and any figure-specific third-party credit; not inferred from first author.',
            permission_route='https://www.nature.com/reprints' if doi.startswith('10.1038/') else 'Consult the official publisher permission page.',
            english_candidate_status='candidate-needs-review' if valid_candidate else 'pending',
            english_candidate=candidate if valid_candidate else None)
        figures[uid]=figure
        if doi not in papers:
            papers[doi]=dict(paper_id=paper_id,doi=doi,title=record['paper'],journal=record['journal'],year=record['year'],
                pdf_source=reference.get('pdf'),pdf_sha256=pdf_hash,article_license=article_license,
                official_evidence=official.get(doi),figure_ids=[],review_status=status,human_reviewed=False)
        papers[doi]['figure_ids'].append(uid)
    review=dict(schema_version=1,papers=papers,figures=figures,diagnostics=diagnostics)
    stats.update(papers=len(papers),papers_matched=sum(bool(p['pdf_source']) for p in papers.values()),
        figures=len(figures),captions_located=sum(f['reference']['status']=='caption-located' for f in figures.values()),
        english_candidates=sum(f['english_candidate_status']=='candidate-needs-review' for f in figures.values()))
    writes.update({output/'catalog.json':encoded(catalog),output/'inventory.json':encoded(inventory),
                   output/'state.json':encoded(state),output/'pdf-review.json':encoded(review)})
    # Small per-paper reports permit incremental human review without opening a
    # single 46-row document; raw captions/quotes are strictly local evidence.
    lines=['# Private PDF and figure review','', 'Automated evidence only. No figure is permitted for publication.','',
           '| Paper / DOI | PDF | License candidate | Figures | Report |','| --- | --- | --- | --- | --- |']
    for doi,paper in sorted(papers.items()):
        filename=doi.replace('/','_')+'.md'
        lines.append(f"| {paper['paper_id']} / {doi} | {paper['pdf_source'] or 'Missing'} | {paper['article_license']['candidate']} | {len(paper['figure_ids'])} | [Review](reviews/{filename}) |")
        report=['# '+paper['title'],'',f"DOI: {doi}",f"Journal / Year: {paper['journal']} / {paper['year']}",
                f"PDF Source: {paper['pdf_source']}",f"Article License candidate: {paper['article_license']['candidate']}",
                '', 'Automated evidence, not final permission. PDF pages are 1-based file pages, not printed page labels.','']
        for uid in paper['figure_ids']:
            f=figures[uid]; cap=f['reference'].get('caption') or {}
            report.extend(['## '+f['figure_id']+' — '+uid,'',f"Review Status: {f['review_status']} (human_reviewed=false)",
                f"Figure Caption Reference: PDF page {cap.get('page','unresolved')}; {cap.get('figure','unresolved')}",
                'Figure-specific Rights / Credit Line: '+f['figure_specific_rights']['note'],
                'Caption credit candidates (full Figure, not automatically every cropped panel): '+json.dumps(f['figure_specific_rights']['candidate_credit_lines'],ensure_ascii=False,sort_keys=True),
                'Evidence Source: '+json.dumps({k:v for k,v in (f['evidence_source'] or {}).items() if k not in ('rights_section',)},ensure_ascii=False,sort_keys=True),
                'Attribution Requirements: '+f['attribution_requirements'],
                'Rights holder: '+f['rights_holder'],'Permission route: '+f['permission_route'],
                'Unresolved Issues: '+' '.join(f['unresolved_issues']),
                'Recommended Action: '+f['recommended_action'],'',
                'English candidate: '+json.dumps(f['english_candidate'],ensure_ascii=False,sort_keys=True),''])
        writes[output/'reviews'/filename]='\n'.join(report).encode('utf-8')
    writes[output/'review-index.md']='\n'.join(lines).encode('utf-8')
    return writes,stats


def verify_sources(source,writes,output):
    review=json.loads(writes[output/'pdf-review.json'])
    for paper in review['papers'].values():
        if paper['pdf_source'] and digest((source/paper['pdf_source']).read_bytes())!=paper['pdf_sha256']:
            raise RuntimeError('Source PDF changed during extraction; existing local snapshot preserved')
    verification_notes = {}
    for record in json.loads(writes[output/'inventory.json'])['records']:
        if current_note_evidence(source,record,verification_notes)!=record.get('current_note_evidence'):
            raise RuntimeError('Source Markdown changed during extraction; rerun after FIG finishes writing')
    for path, (text, _) in verification_notes.items():
        if path.read_text(encoding='utf-8-sig') != text:
            raise RuntimeError('Source Markdown changed during verification; existing local snapshot preserved')


def run(source,output,dry_run=False):
    from import_gallery import ROOT,check_safety,atomic_write,OVERLAY
    source=source.resolve(strict=True);output=output.resolve()
    check_safety(output,source)
    catalog=load(output/'catalog.json',{});inventory=load(output/'inventory.json',{});state=load(output/'state.json',{})
    if not all('records' in v for v in (catalog,inventory,state)):
        raise ValueError('Import local FIG records before PDF enrichment')
    writes,stats=build(source,output,catalog,inventory,state)
    overlay=OVERLAY.replace("source = '.gallery-local/assets'",'source = '+json.dumps((output/'assets').relative_to(ROOT).as_posix())).replace("galleryCatalog = '.gallery-local/catalog.json'",'galleryCatalog = '+json.dumps((output/'catalog.json').relative_to(ROOT).as_posix())).replace('CATALOG_REVISION',digest(writes[output/'catalog.json']))
    writes[output/'hugo.toml']=overlay.encode()
    changed={str(p.relative_to(ROOT)):'update' if p.exists() else 'create' for p,b in writes.items() if not p.exists() or p.read_bytes()!=b}
    if any(not p.resolve().is_relative_to(output) for p in writes):
        raise ValueError('PDF evidence output escapes the ignored local directory')
    if not dry_run:
        # Refuse a mixed snapshot if FIG replaces a PDF while extraction runs.
        verify_sources(source,writes,output)
        for path,content in writes.items():atomic_write(path,content)
    return dict(summary=stats,files=changed,dry_run=dry_run)


def main():
    from import_gallery import LOCAL,DEFAULT_SOURCE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path);parser.add_argument('--output',type=Path,default=LOCAL)
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    try:
        source=args.source or Path(load(args.output/'settings.json',{}).get('source',DEFAULT_SOURCE))
        report=run(source,args.output,args.dry_run)
        print(json.dumps(report if args.json else report['summary'],ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError,RuntimeError,KeyError,ImportError) as exc:
        print('STOP: '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
