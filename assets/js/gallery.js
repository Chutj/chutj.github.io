(() => {
  'use strict';
  const data = document.getElementById('gallery-data');
  if (!data) return;
  let raw;
  try { raw = JSON.parse(data.textContent); } catch { raw = []; }
  const publicMode = data.dataset.mode === 'public';
  const publicHosts = (data.dataset.imageHosts || '').split(',').filter(Boolean);
  const safePath = value => {
    if (typeof value !== 'string') return '';
    if (!publicMode) return /^\/(?!\/)[^\\]*$/.test(value) ? value : '';
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash
        && publicHosts.includes(url.host) ? value : '';
    } catch { return ''; }
  };
  const figures = (Array.isArray(raw) ? raw : []).map(f => ({
    ...f, title: f.title || 'Untitled figure', primary: f.primary || 'Uncategorized',
    categories: Array.isArray(f.categories) ? f.categories.filter(v => typeof v === 'string') : [],
    sections: f.sections && typeof f.sections === 'object' ? f.sections : {},
    image: safePath(f.image), thumbnail: safePath(f.thumbnail),
    width: Number(f.width) > 0 ? Number(f.width) : 4,
    height: Number(f.height) > 0 ? Number(f.height) : 3,
  }));
  document.body.classList.add('gallery-page');
  const query = document.getElementById('gallery-query');
  const category = document.getElementById('gallery-category');
  const sort = document.getElementById('gallery-sort');
  const grid = document.getElementById('gallery-grid');
  const dialog = document.getElementById('figure-detail');
  const image = document.getElementById('detail-image');
  const viewport = document.getElementById('detail-viewport');
  const count = document.getElementById('gallery-count');
  let opener, activeFigure, zoom = 1, pendingLayout = 0;
  const text = (id, value) => { document.getElementById(id).textContent = value || ''; };
  const meta = figure => [figure.journal, figure.year, figure.figure].filter(Boolean).join(' · ') || 'Source information unavailable';
  const categories = [...new Set(figures.flatMap(f => f.categories))].sort();
  categories.forEach(name => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = `${name} (${figures.filter(f => f.categories.includes(name)).length})`;
    category.append(option);
  });
  function layout() {
    pendingLayout = 0;
    const style = getComputedStyle(grid);
    const columns = Number(style.getPropertyValue('--gallery-columns')) || 1;
    const gap = Number.parseFloat(style.getPropertyValue('--gallery-gap')) || 12;
    const width = (grid.clientWidth - gap * (columns - 1)) / columns;
    if (width <= 0) return;
    const cards = [...grid.children];
    grid.classList.add('is-masonry');
    cards.forEach(card => { card.style.width = `${width}px`; });
    // DOM/tab order remains the sorted catalog order. Each next card starts at
    // the lowest available top position, leftmost column on ties.
    const heights = new Array(columns).fill(0);
    const measured = cards.map(card => card.getBoundingClientRect().height);
    cards.forEach((card, index) => {
      const column = heights.indexOf(Math.min(...heights));
      card.style.transform = `translate(${column * (width + gap)}px, ${heights[column]}px)`;
      heights[column] += measured[index] + gap;
    });
    grid.style.height = `${cards.length ? Math.max(...heights) - gap : 0}px`;
  }
  function scheduleLayout() {
    if (!pendingLayout) pendingLayout = requestAnimationFrame(layout);
  }
  const resizeObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(scheduleLayout) : null;
  resizeObserver?.observe(grid);
  window.addEventListener('resize', scheduleLayout);
  document.fonts?.ready.then(scheduleLayout);
  function setZoom(value) {
    if (!activeFigure) return;
    zoom = Math.max(0.05, Math.min(4, value));
    image.style.width = `${activeFigure.width * zoom}px`;
    text('zoom-level', `${Math.round(zoom * 100)}%`);
  }
  function fitImage() {
    if (!activeFigure) return;
    setZoom(Math.min(1, (viewport.clientWidth - 2) / activeFigure.width,
      window.innerHeight * 0.65 / activeFigure.height));
    viewport.scrollTo(0, 0);
  }
  image.addEventListener('error', () => {
    image.hidden = true;
    text('zoom-level', 'Image unavailable');
    document.getElementById('detail-image-error').hidden = false;
  });
  function openFigure(figure, button) {
    opener = button; activeFigure = figure;
    text('detail-title', figure.title); text('detail-meta', meta(figure));
    text('detail-categories', figure.categories.length ? `Filed under: ${figure.categories.join(' · ')}` : 'Category unavailable');
    text('detail-paper', figure.paper || 'Paper title unavailable');
    text('detail-translation', !figure.translation_status || figure.translation_status === 'reviewed'
      ? 'English translation of the existing library notes. Verification statements describe the source notes, not a new literature review.'
      : 'English translation pending review. Original notes are retained in the local inventory. Any PDF-based candidate below is a draft requiring human review.');
    text('detail-author', figure.author ? `First author: ${figure.author}` : 'Author information unavailable');
    const rights = document.getElementById('detail-rights');
    rights.hidden = !publicMode;
    rights.textContent = publicMode ? `Attribution: ${figure.rights.attribution} · License: ${figure.rights.license}` : '';
    if (publicMode && typeof figure.rights.license_url === 'string'
        && figure.rights.license_url.startsWith('https://')) {
      const license = document.createElement('a'); license.href = figure.rights.license_url;
      license.textContent = ' License terms'; license.target = '_blank'; license.rel = 'noopener';
      rights.append(license);
    }
    image.hidden = !figure.image;
    document.getElementById('detail-image-error').hidden = Boolean(figure.image);
    image.removeAttribute('src'); image.alt = figure.title;
    image.width = figure.width; image.height = figure.height;
    if (figure.image) image.src = figure.image;
    const original = document.getElementById('detail-original');
    original.hidden = !figure.image; original.removeAttribute('href');
    if (figure.image) original.href = figure.image;
    const doi = document.getElementById('detail-doi');
    doi.removeAttribute('href');
    const validDOI = typeof figure.doi === 'string' && /^10\.\d{4,9}\/\S+$/.test(figure.doi);
    doi.textContent = validDOI ? `DOI: ${figure.doi}` : 'DOI unavailable';
    if (validDOI) doi.href = `https://doi.org/${figure.doi}`;
    const notes = document.getElementById('detail-notes'); notes.replaceChildren();
    ['What the figure shows', 'Statistics & symbols', 'Color & encoding',
      'Design lessons', 'Verification & limitations'].forEach(heading => {
      const section = document.createElement('section');
      const h3 = document.createElement('h3'); h3.textContent = heading;
      const p = document.createElement('p'); p.textContent = figure.sections[heading] || 'Not recorded in the source notes.';
      section.append(h3, p); notes.append(section);
    });
    if (!publicMode && figure.pdf_reference) {
      const ref = figure.pdf_reference;
      const section = document.createElement('section');
      const heading = document.createElement('h3'); heading.textContent = 'Local PDF evidence and review';
      const summary = document.createElement('p');
      summary.textContent = `${ref.figure || figure.figure} · PDF page ${ref.page || 'unresolved'} · Article license candidate: ${ref.article_license || 'unverified'} · Review: ${ref.review_status || 'unverified'}. No publication permission has been granted.`;
      section.append(heading, summary);
      if (ref.candidate_title) {
        const title = document.createElement('h3'); title.textContent = `English draft — ${ref.candidate_title}`;
        section.append(title);
      }
      ['What the figure shows', 'Statistics & symbols', 'Color & encoding',
        'Design lessons', 'Verification & limitations'].forEach(label => {
        const value = (ref.candidate || {})[label];
        if (!value) return;
        const h = document.createElement('h4'); h.textContent = label;
        const p = document.createElement('p'); p.textContent = value;
        section.append(h, p);
      });
      notes.append(section);
    }
    dialog.showModal(); document.body.classList.add('gallery-modal-open');
    dialog.scrollTop = 0; fitImage();
  }
  function render() {
    const terms = query.value.toLocaleLowerCase('en').trim().split(/\s+/).filter(Boolean);
    const matches = figures.filter(figure => {
      const haystack = [figure.title, figure.paper, figure.author, figure.doi,
        figure.journal, figure.figure, figure.year, ...figure.categories,
        ...Object.values(figure.sections), ...(!publicMode ?
          [figure.pdf_reference?.candidate_title, ...Object.values(figure.pdf_reference?.candidate || {})] : [])
      ].join(' ').toLocaleLowerCase('en');
      return (!category.value || figure.categories.includes(category.value)) && terms.every(t => haystack.includes(t));
    });
    if (sort.value === 'title') matches.sort((a, b) => a.title.localeCompare(b.title, 'en'));
    if (sort.value === 'newest') matches.sort((a, b) => (Number(b.year) || 0) - (Number(a.year) || 0) || a.title.localeCompare(b.title, 'en'));
    [...grid.children].forEach(card => resizeObserver?.unobserve(card));
    grid.replaceChildren();
    matches.forEach(figure => {
      const article = document.createElement('article'); article.className = 'figure-card';
      const button = document.createElement('button'); button.type = 'button';
      button.setAttribute('aria-label', `View figure: ${figure.title}`);
      const unavailable = document.createElement('span'); unavailable.className = 'figure-image-missing';
      unavailable.textContent = 'Image unavailable'; unavailable.hidden = Boolean(figure.thumbnail);
      const img = document.createElement('img'); img.alt = ''; img.loading = 'lazy'; img.decoding = 'async';
      img.width = figure.width; img.height = figure.height;
      img.style.aspectRatio = `${figure.width} / ${figure.height}`;
      img.style.objectFit = 'contain';
      img.hidden = !figure.thumbnail;
      img.addEventListener('error', () => { img.hidden = true; unavailable.hidden = false; scheduleLayout(); }, { once: true });
      img.addEventListener('load', scheduleLayout, { once: true });
      if (figure.thumbnail) {
        if (figure.srcset && figure.srcset.split(',').every(part => safePath(part.trim().split(/\s+/)[0]))) img.srcset = figure.srcset;
        img.sizes = '(min-width: 1230px) 380px, (min-width: 1100px) 31vw, (min-width: 360px) 46vw, 92vw';
        img.src = figure.thumbnail;
      }
      const body = document.createElement('div'); body.className = 'figure-card-body';
      const label = document.createElement('span'); label.className = 'figure-category'; label.textContent = figure.primary;
      const title = document.createElement('h2'); title.textContent = figure.title;
      const source = document.createElement('p'); source.textContent = meta(figure);
      const action = document.createElement('span'); action.className = 'figure-action'; action.textContent = 'View figure & notes →';
      body.append(label, title, source, action); button.append(img, unavailable, body); article.append(button); grid.append(article);
      resizeObserver?.observe(article);
      button.addEventListener('click', () => openFigure(figure, button));
    });
    count.textContent = `${matches.length} of ${figures.length} figures`;
    document.getElementById('gallery-empty').hidden = matches.length > 0;
    layout();
  }
  query.addEventListener('input', render); category.addEventListener('change', render); sort.addEventListener('change', render);
  document.getElementById('gallery-reset').addEventListener('click', () => {
    query.value = ''; category.value = ''; sort.value = 'library'; render(); query.focus();
  });
  document.getElementById('zoom-fit').addEventListener('click', fitImage);
  document.getElementById('zoom-actual').addEventListener('click', () => setZoom(1));
  document.getElementById('zoom-out').addEventListener('click', () => setZoom(zoom / 1.5));
  document.getElementById('zoom-in').addEventListener('click', () => setZoom(zoom * 1.5));
  dialog.addEventListener('keydown', e => {
    if (e.key === '+' || e.key === '=') { e.preventDefault(); setZoom(zoom * 1.5); }
    if (e.key === '-') { e.preventDefault(); setZoom(zoom / 1.5); }
    if (e.key === '0') { e.preventDefault(); fitImage(); }
    if (e.key === '1') { e.preventDefault(); setZoom(1); }
  });
  document.getElementById('detail-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', e => { if (e.target === dialog) {
    const rect = dialog.getBoundingClientRect();
    if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) dialog.close();
  }});
  dialog.addEventListener('close', () => {
    document.body.classList.remove('gallery-modal-open');
    // Do not leave a full-resolution src active on the overview page.
    image.removeAttribute('src'); activeFigure = null;
    if (opener?.isConnected) opener.focus();
  });
  window.addEventListener('resize', () => { if (dialog.open) fitImage(); });
  render();
})();
