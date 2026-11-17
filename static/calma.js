/* Calma — movimiento común de las apps (fuente: ~/estilo/calma.js, copiada por aplica.sh).
   Todo respeta "reducir movimiento" del sistema: si está activo, no se anima nada. */
const calma = (() => {
  const quieto = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Apariencia (Ajustes → Apariencia) ----------
     El catálogo es /apariencia.json (de ~/estilo, el mismo que usa Tom) y lo elegido viene de /api/apariencia.
     Para no pintar ni un fotograma con los colores de antes, lo último calculado se guarda en localStorage
     (calma-tema) y se aplica aquí mismo, en el <head>, antes de que se vea nada. Luego se pide lo nuevo. */
  const raiz = document.documentElement;
  const leeLocal = (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } };
  const ponLocal = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } };
  const oscuroSistema = matchMedia("(prefers-color-scheme: dark)");
  let tema = leeLocal("calma-tema");
  const conAlfa = (c, k) => {
    const m = /^rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)$/.exec(c || "");
    if (m) return `rgba(${m[1]}, ${m[2]}, ${m[3]}, ${Math.min(1, +m[4] * k).toFixed(3)})`;
    const h = /^#([0-9a-f]{6})$/i.exec(c || "");
    if (h) { const n = parseInt(h[1], 16); return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${Math.min(1, k).toFixed(3)})`; }
    return c;
  };
  const FOTOS = {hoy: ["nube", "estanque"], todo: ["nube", "estanque"], pendientes: ["terrazas", "arboles"], gastos: ["sendero", "estanque"],
    salud: ["sendero", "arboles"], carrera: ["sendero", "estanque"], entreno: ["terrazas", "arboles"], ajustes: ["nube", "arboles"],
    documentos: ["terrazas", "estanque"], limpieza: ["terrazas", "arboles"]};
  function pintaTema() {
    if (!tema || !tema.claro) return;
    const oscuro = tema.modo === "oscuro" || (tema.modo !== "claro" && oscuroSistema.matches);
    const v = oscuro ? tema.oscuro : tema.claro;
    for (const [k, x] of Object.entries(v)) raiz.style.setProperty(k, x);
    for (const [k, x] of Object.entries(tema.comun)) raiz.style.setProperty(k, x);
    raiz.style.colorScheme = tema.modo === "sistema" ? "" : (oscuro ? "dark" : "light");
    raiz.dataset.modo = oscuro ? "oscuro" : "claro";
    // la carcasa (Ajustes → Aparato): hardware.css cuelga todo de html[data-aparato="hardware"]; Calma no lleva atributo
    if (tema.aparato && tema.aparato !== "calma") raiz.dataset.aparato = tema.aparato; else delete raiz.dataset.aparato;
    // Solarpunk (solar.css): cada página abre con su foto, una de día y otra de noche (los créditos van en el CSS)
    if (tema.aparato === "solar") raiz.dataset.foto = (FOTOS[document.title.trim().toLowerCase()] || FOTOS.hoy)[oscuro ? 1 : 0];
    else delete raiz.dataset.foto;
    for (const m of document.querySelectorAll('meta[name="theme-color"]')) m.content = v["--fondo"];
    dispatchEvent(new Event("calma-tema"));
  }
  /* ---- color: hex ↔ OKLCH. genera() es LA fórmula de los temas; Tom (Aspecto.swift) la repite igual ---- */
  const lin = c => (c /= 255) <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4;
  const gam = x => { x = Math.max(0, Math.min(1, x)); return Math.round((x <= .0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - .055) * 255); };
  function aOklch(hex) {
    const n = parseInt(String(hex).replace("#", ""), 16) || 0;
    const r = lin(n >> 16), g = lin((n >> 8) & 255), b = lin(n & 255);
    const l = Math.cbrt(.4122214708 * r + .5363325363 * g + .0514459929 * b), m = Math.cbrt(.2119034982 * r + .6806995451 * g + .1073969566 * b),
          s = Math.cbrt(.0883024619 * r + .2817188376 * g + .6299787005 * b);
    const L = .2104542553 * l + .793617785 * m - .0040720468 * s, A = 1.9779984951 * l - 2.428592205 * m + .4505937099 * s,
          B = .0259040371 * l + .7827717662 * m - .808675766 * s;
    return [L * 100, Math.hypot(A, B), (Math.atan2(B, A) * 180 / Math.PI + 360) % 360];
  }
  function deOklch(L, C, H, alfa) {
    const h = H * Math.PI / 180, A = C * Math.cos(h), B = C * Math.sin(h), l0 = L / 100;
    const l = (l0 + .3963377774 * A + .2158037573 * B) ** 3, m = (l0 - .1055613458 * A - .0638541728 * B) ** 3, s = (l0 - .0894841775 * A - 1.291485548 * B) ** 3;
    const rgb = [4.0767416621 * l - 3.3077115913 * m + .2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - .3413193965 * s,
                 -.0041960863 * l - .7034186147 * m + 1.707614701 * s].map(gam);
    return alfa == null ? "#" + rgb.map(x => x.toString(16).padStart(2, "0")).join("").toUpperCase() : `rgba(${rgb.join(", ")}, ${alfa})`;
  }
  const entre = (x, a, b) => Math.max(a, Math.min(b, x));
  function genera(base, acento) {
    const [Lb, Cb0, Hb] = aOklch(base), cn = Cb0 < .004 ? 0 : Math.min(Cb0, .045), hn = Hb;
    const fc = Lb >= 90 ? Math.min(Lb, 99) : 96.8, fo = Lb <= 25 ? Math.max(Lb, 7) : 18.5;
    const N = (L, k, a) => deOklch(L, cn * k, hn, a);
    const claro = {fondo: N(fc, .45), carta: N(Math.min(fc + 2.8, 100), .12), carta_luz: "#FFFFFF", carta2: N(fc - 3.2, .6), texto: N(22, .7),
                   suave: N(52, .6), tenue: N(70, .5), linea: N(fc - 6.3, .55), dock: N(30, .8), dock_texto: N(78, .5), ascii: N(30, 1, .2)};
    const oscuro = {fondo: N(fo, .6), carta: N(fo + 4.5, .7), carta_luz: N(fo + 7, .7), carta2: N(fo + 8.5, .75), texto: N(95, .3),
                    suave: N(72, .55), tenue: N(52, .5), linea: N(fo + 13.5, .75), dock: N(Math.max(fo + 11.5, 26), .8), dock_texto: N(78, .5), ascii: N(90, 1.4, .15)};
    const [La, Ca0, Ha] = aOklch(acento), ca = Math.min(Ca0, .25);
    const A = (L, k) => deOklch(L, ca * k, Ha);
    const ac = {claro: {acento: A(entre(La, 38, 58), 1), texto: "#FFFFFF", suave: A(95, .25)},
                oscuro: {acento: A(entre(La, 72, 88), .9), texto: A(22, .6), suave: A(31, .35)},
                gota: A(entre(La, 78, 90), .9), gota_texto: A(24, .7)};
    return {claro, oscuro, ac};
  }
  /* catálogo + elección → las variables CSS de claro y oscuro (lo que se guarda en calma-tema) */
  function calculaTema(cat, el) {
    const def = cat.defecto, busca = (l, id, d) => cat[l].find(x => x.id === id) || cat[l].find(x => x.id === d);
    const hex = (x, d) => /^#[0-9a-f]{6}$/i.test(x || "") ? x : d;
    const g = genera(hex(el.base, def.base), hex(el.acento, def.acento));
    const fu = busca("fuentes", el.fuente, def.fuente), ti = busca("fuentes", el.titulos || el.fuente, def.titulos), es = busca("esquinas", el.esquinas, def.esquinas);
    const fo = busca("fondos", el.fondo, def.fondo), k = fo.intensidad;
    const pila = f => `${f.css}, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
    const lado = (n, a, f, claro) => ({
      "--fondo": n.fondo, "--carta": n.carta, "--carta-luz": n.carta_luz, "--carta-2": n.carta2, "--texto": n.texto,
      "--suave": n.suave, "--tenue": n.tenue, "--linea": n.linea, "--dock": n.dock, "--dock-texto": n.dock_texto,
      "--acento": a.acento, "--acento-texto": a.texto, "--acento-suave": a.suave, "--franja": claro ? n.texto : n.fondo,
      "--ascii": conAlfa(n.ascii, k * .5), "--ascii-vivo": conAlfa(a.acento, (claro ? .45 : .4) * Math.min(1.4, k)),
      "--peligro": f.peligro, "--peligro-suave": f.peligro_suave, "--aviso": f.aviso, "--aviso-suave": f.aviso_suave,
    });
    const aparato = (cat.aparatos || []).some(x => x.id === el.aparato) ? el.aparato : "calma";
    return {modo: el.modo || "sistema", fondo: fo.id, intensidad: k, aparato,
            claro: lado(g.claro, g.ac.claro, cat.fijos.claro, true), oscuro: lado(g.oscuro, g.ac.oscuro, cat.fijos.oscuro, false),
            comun: {"--gota": g.ac.gota, "--gota-texto": g.ac.gota_texto, "--r": es.carta + "px", "--r-s": es.boton + "px", "--r-xs": es.celda + "px",
                    "--fuente": pila(fu), "--fuente-titulos": pila(ti)}};
  }
  /* las letras que no son la de siempre: su @font-face se mete al elegirlas (y solo se descarga la que se usa) */
  function cargaFuentes(cat, ids) {
    for (const f of cat.fuentes.filter(x => ids.includes(x.id) && x.web)) {
      if (document.getElementById("ff-" + f.id)) continue;
      const fam = f.css.replace(/"/g, ""), caras = f.pesos === "estaticos"
        ? [400, 700].map(w => `@font-face{font-family:"${fam}";font-weight:${w};font-display:swap;src:url("/fuentes/${f.web}-${w}.woff2?v=1") format("woff2")}`)
        : [`@font-face{font-family:"${fam}";font-weight:${f.pesos};font-display:swap;src:url("/fuentes/${f.web}.woff2?v=1") format("woff2")}`];
      if (f.web.endsWith("-latin")) continue;   // las de calma.css ya están declaradas
      const st = Object.assign(document.createElement("style"), {id: "ff-" + f.id, textContent: caras.join("")});
      document.head.append(st);
    }
  }
  if (tema?.caras) document.head.append(Object.assign(document.createElement("style"), {id: "ff-cache", textContent: tema.caras}));
  pintaTema();
  oscuroSistema.addEventListener?.("change", pintaTema);
  let catalogo = null;
  const pideCatalogo = () => catalogo ? Promise.resolve(catalogo)
    : fetch("/apariencia.json", {credentials: "same-origin"}).then(r => r.ok ? r.json() : Promise.reject()).then(c => (catalogo = c));
  /* aplica una elección (de /api/apariencia o de Ajustes, al momento) y la recuerda */
  async function ponApariencia(el) {
    const cat = await pideCatalogo();
    tema = calculaTema(cat, el || {});
    tema.eleccion = el || {};
    cargaFuentes(cat, [el?.fuente, el?.titulos].filter(Boolean));
    tema.caras = [...document.querySelectorAll('style[id^="ff-"]')].map(x => x.textContent).join("");
    ponLocal("calma-tema", tema);
    pintaTema();
    return tema;
  }
  // lo guardado en el servidor; sin red o sin /api/apariencia, lo de la última vez
  const disposicionLista = fetch("/api/apariencia", {credentials: "same-origin"})
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(d => {
      if (d.apariencia && JSON.stringify(d.apariencia) !== JSON.stringify(tema?.eleccion)) ponApariencia(d.apariencia).catch(() => {});
      if (d.disposicion) ponLocal("calma-disposicion", d.disposicion);
      return d.disposicion || leeLocal("calma-disposicion") || {};
    })
    .catch(() => leeLocal("calma-disposicion") || {});

  /* Páginas con <meta name="calma-entrada">: el contenido espera oculto hasta que llegan los datos y
     anima.entra() lo hace entrar una sola vez, sin pintarse antes con «—» ni dar saltos. Con la red
     caída sale igual a los 8 s. (Este fichero va en el <head>: actúa antes de que se pinte nada.) */
  if (!quieto() && document.querySelector('meta[name="calma-entrada"]')) {
    document.documentElement.classList.add("c-cargando");
    setTimeout(() => document.documentElement.classList.remove("c-cargando"), 8000);
  }

  /* Si iOS recarga la app instalada en mitad de un entreno (pantalla bloqueada, poca memoria), arranca en la
     portada: Entreno deja apuntado lo que estaba en marcha y desde aquí se vuelve, antes de pintar nada. */
  try {
    const m = JSON.parse(localStorage.getItem("entreno-en-marcha"));
    if (m && location.pathname === "/" && m.hasta > Date.now() && m.dia === new Date().toLocaleDateString("sv")) location.replace(m.url);
  } catch { /* sin almacenamiento, nada que reanudar */ }

  /* <meta name="calma-datos" content="/api/hoy,/api/otra">: esas peticiones salen ya, desde el <head>,
     a la vez y sin esperar al resto de scripts. El primer fetch() de la página a cada una recibe esa
     misma respuesta (una vez); los siguientes van a la red como siempre. */
  const pedidas = new Map();
  for (const u of (document.querySelector('meta[name="calma-datos"]')?.content || "").split(",").map(s => s.trim()).filter(Boolean))
    pedidas.set(u, fetch(u, {credentials: "same-origin"}));
  if (pedidas.size) {
    const red = window.fetch.bind(window);
    window.fetch = (u, op) => {
      if (typeof u === "string" && pedidas.has(u) && !(op && op.method && op.method !== "GET")) {
        const r = pedidas.get(u);
        pedidas.delete(u);
        return r;
      }
      return red(u, op);
    };
  }

  /* Cambio de pestaña o de mes con fundido. View Transitions es nativo (Safari 18, Chrome):
     donde no existe, se ejecuta tal cual. */
  let animando = 0;   // transiciones en marcha: mientras tanto el fondo no se repinta (se lo come el fundido)
  // algo se está animando encima (transición, hoja de cristal, la página que se va): los fondos no se repintan
  const ocupado = () => animando > 0 || !!document.querySelector(".c-velo.on, .c-hoja.on")
                        || document.documentElement.classList.contains("c-saliendo");
  function transicion(fn) {
    // con la pestaña oculta Chrome aborta la transición (InvalidStateError) y fn no llega a pintar
    if (quieto() || !document.startViewTransition || document.visibilityState !== "visible") return fn();
    const vt = document.startViewTransition(fn);
    animando++;
    vt.ready.catch(() => {});
    vt.finished.catch(() => {}).finally(() => animando--);
  }

  /* El service worker da los datos de su copia si la red tarda, y avisa si luego llegan distintos: se
     recargan con la función de la página (refresca, la de hábitos y entreno, respeta lo que esté a medias). */
  navigator.serviceWorker?.addEventListener("message", e => {
    if (e.data?.tipo !== "fresco") return;
    const f = window.refresca || window.cargar;
    if (typeof f === "function") f();
  });

  /* Un número que sube hasta su valor: 0 → 1.234,56 €. fmt convierte el número en texto. */
  function cuenta(el, valor, fmt = String, ms = 650) {
    const desde = Number(el.dataset.valor || 0);
    el.dataset.valor = valor;
    if (quieto() || desde === valor) { el.textContent = fmt(valor); return; }
    const t0 = performance.now();
    const paso = t => {
      const p = Math.min(1, (t - t0) / ms), e = 1 - (1 - p) ** 3;   // ease-out cúbico
      el.textContent = fmt(desde + (valor - desde) * e);
      if (p < 1) requestAnimationFrame(paso);
    };
    requestAnimationFrame(paso);
  }

  /* Confeti para los logros (canvas-confetti, se carga solo la primera vez que hace falta).
     clave: una vez por clave y día, para que no salga en cada recarga. */
  let lib;
  async function fiesta(clave) {
    if (quieto()) return;
    const marca = `calma.fiesta.${clave}.${new Date().toLocaleDateString("sv")}`;
    try { if (localStorage.getItem(marca)) return; localStorage.setItem(marca, "1"); } catch {}
    lib ||= new Promise((ok, mal) => {
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.js";
      s.onload = () => ok(window.confetti);
      s.onerror = mal;
      document.head.append(s);
    });
    try {
      const confetti = await lib;
      const css = getComputedStyle(document.documentElement);
      const colores = ["--acento", "--serie-1", "--serie-4", "--serie-5"].map(v => css.getPropertyValue(v).trim());
      confetti({particleCount: 90, spread: 70, startVelocity: 38, origin: {y: .75}, colors: colores, disableForReducedMotion: true});
    } catch { /* sin red no hay confeti, y no pasa nada */ }
  }

  /* El menú de todo (en todas sus páginas, también en gastos.html) se rehace como la
     barra de abajo: todas las secciones, siempre en el mismo sitio, y la actual es una gota que sale
     de la barra. Al tocar otra, la gota se desliza hasta ella y luego se navega.
     Solo toca el nav que enlaza a pendientes, entreno o carrera. */
  const I = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
  const MENU = [
    ["/", "Hoy", I('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>')],
    ["/habitos.html", "Hábitos", I('<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.5"/>')],
    ["/pendientes.html", "Pendientes", I('<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>')],
    ["/entreno.html", "Entreno", I('<path d="M6.5 6.5v11M17.5 6.5v11M3.5 9v6M20.5 9v6M6.5 12h11"/>')],
    ["/salud.html", "Salud", I('<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>')],
    ["/gastos.html", "Gastos", I('<rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10h18M16 15h2"/>')],
    ["/calendario.html", "Calendario", I('<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>')],
    ["/documentos.html", "Docs", I('<path d="M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 16h5"/>')],
    ["/inversiones.html", "Inversión", I('<path d="M3.5 19.5h17M5 15.5l4.5-4.5 3.5 3 6.5-7M15 7h4v4"/>')],
  ];
  /* Lo que cada usuario ha elegido en Ajustes: mascota.js lo deja aquí al llegar del servidor, y así la
     barra y el saludo salen bien desde el primer momento en la página siguiente. */
  const perfil = () => { try { return JSON.parse(localStorage.getItem("calma-perfil")) || {}; } catch { return {}; } };
  let rehaz = () => {};
  function ponPerfil(p) {
    const antes = JSON.stringify(perfil().barra);
    try { localStorage.setItem("calma-perfil", JSON.stringify(p)); } catch { /* sin almacenamiento, la barra entera */ }
    if (JSON.stringify(p.barra) !== antes) rehaz();
  }
  function saludo(hora) {
    const n = perfil().nombre;
    return `${hora < 6 || hora >= 21 ? "Buenas noches" : hora < 14 ? "Buenos días" : "Buenas tardes"}${n ? `, ${n}` : ""}`;
  }
  function menu() {
    const nav = [...document.querySelectorAll("nav")].find(n => n.querySelector('a[href="/pendientes.html"], a[href="/entreno.html"], a[href="/carrera.html"]'));
    if (!nav) return;
    // Hoy es la portada (/, y también /hoy.html); Hábitos vive en /habitos.html (y /index.html)
    const aqui = {"/hoy.html": "/", "/index.html": "/habitos.html", "/carrera.html": "/entreno.html", "/sueno.html": "/salud.html"}[location.pathname] || location.pathname;
    if (!document.getElementById("c-goo")) document.body.insertAdjacentHTML("beforeend",
      // difumina, endurece el borde (la unión se funde) y vuelve a pintar encima lo original, nítido
      '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><filter id="c-goo" color-interpolation-filters="sRGB">' +
      '<feGaussianBlur in="SourceGraphic" stdDeviation="7" result="b"/>' +
      '<feColorMatrix in="b" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -8" result="goo"/>' +
      '<feComposite in="SourceGraphic" in2="goo" operator="atop"/></filter></svg>');
    const goo = Object.assign(document.createElement("div"), {className: "c-goo", innerHTML: '<span class="c-tira"></span><span class="c-gota"></span>'});
    const gota = goo.lastChild;
    nav.className = "c-dock";   // fuera las clases de cada página (.menu-todo): manda calma.css
    nav.setAttribute("aria-label", "Menú");
    const enlaces = () => MENU.filter(([href]) => href === "/" || !perfil().barra || perfil().barra.includes(href)).map(([href, nombre, icono]) => {
      const a = Object.assign(document.createElement("a"), {href, innerHTML: `${icono}<span>${nombre}</span>`});
      if (href === aqui) a.setAttribute("aria-current", "page");
      return a;
    });
    const pinta = () => { nav.replaceChildren(goo, ...enlaces()); nav.style.setProperty("--n", nav.querySelectorAll("a").length); };
    pinta();
    document.body.append(nav);   // fuera de la cabecera: el mismo sitio en todas las páginas
    const actual = () => nav.querySelector('a[aria-current="page"]');
    const pon = (a, animada) => {
      gota.style.transition = animada ? "" : "none";
      gota.style.transform = `translateX(${a.offsetLeft + a.offsetWidth / 2 - 26}px)`;
    };
    const coloca = () => { gota.hidden = !actual(); if (actual()) pon(actual(), false); };
    coloca();
    rehaz = () => { pinta(); coloca(); };
    addEventListener("resize", coloca);
    nav.addEventListener("click", e => {
      const a = e.target.closest("a");
      if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return;
      if (a === actual()) return e.preventDefault();
      if (quieto()) return;
      e.preventDefault();
      actual()?.removeAttribute("aria-current");
      a.setAttribute("aria-current", "page");
      gota.hidden = false;
      pon(a, true);
      vete(a.href, entrePaginas() ? 90 : 120);   // la gota arranca y la página se va enseguida (antes 320 ms en cada toque)
    });
    /* arrastrar el dedo por la barra: la gota lo sigue, cada sección por la que pasa vibra y al soltar se va a esa */
    let arrastre = null;
    const bajo = x => [...nav.querySelectorAll("a")].find(a => { const r = a.getBoundingClientRect(); return x >= r.left && x < r.right; });
    nav.addEventListener("pointerdown", e => { if (e.pointerType !== "mouse") arrastre = {x0: e.clientX, mueve: false, sobre: bajo(e.clientX)}; });
    nav.addEventListener("pointermove", e => {
      if (!arrastre) return;
      if (!arrastre.mueve && Math.abs(e.clientX - arrastre.x0) < 8) return;
      if (!arrastre.mueve) { arrastre.mueve = true; try { nav.setPointerCapture(e.pointerId); } catch {} }
      const r = nav.getBoundingClientRect(), x = Math.max(r.left + 26, Math.min(r.right - 26, e.clientX));
      gota.hidden = false; gota.style.transition = "none";
      gota.style.transform = `translateX(${x - r.left - 26}px)`;
      const a = bajo(e.clientX);
      if (a && a !== arrastre.sobre) {
        arrastre.sobre = a; vibra();
        nav.querySelectorAll("a").forEach(x => x.toggleAttribute("aria-current", x === a));
        nav.querySelectorAll("a[aria-current]").forEach(x => x.setAttribute("aria-current", "page"));
      }
    });
    const suelta = e => {
      if (!arrastre) return;
      const {mueve, sobre} = arrastre;
      arrastre = null;
      if (!mueve) return;   // fue un toque: lo lleva el click
      e.preventDefault();
      if (sobre) { pon(sobre, true); if (sobre.href !== location.href) vete(sobre.href, 160); }
      // y el click que viene detrás de soltar no cuenta
      nav.addEventListener("click", x => x.preventDefault(), {once: true, capture: true});
    };
    nav.addEventListener("pointerup", suelta);
    nav.addEventListener("pointercancel", () => { arrastre = null; coloca(); });
    nav.style.touchAction = "none";
  }
  /* App instalada en un iPhone con isla dinámica (barra de estado de 51 px o más): los avisos salen de ella */
  function islaReal() {
    const sonda = Object.assign(document.createElement("div"), {style: "position:fixed;top:0;height:env(safe-area-inset-top,0px);visibility:hidden"});
    document.body.append(sonda);
    if (navigator.standalone && sonda.offsetHeight >= 51) document.documentElement.classList.add("c-isla-real");
    sonda.remove();
  }
  /* Fondo: un «shader» de caracteres ASCII. Canvas 2D, una llamada por fila y color, a 12 fotogramas por segundo;
     parado con la pestaña oculta y quieto con «reducir movimiento». Tampoco se repinta mientras haces scroll, hay una
     transición, una hoja de cristal (su desenfoque se recalcularía con cada fotograma de debajo) o la página se va; y sin
     tocar nada en 8 s, va a 6 por segundo. Se aviva alrededor del dedo y una onda sale de donde marcas algo.
     Tres dibujos, con data-fondo en el <body> o en una carta (que lo lleva dentro, con su forma):
     - (nada): un plasma de senos decide qué carácter toca (de « » a «@»).
     - "plano": rejilla de papel milimetrado, + - | y puntos, con un brillo que la recorre despacio.
     - "curvas": curvas de nivel de un relieve de ruido que se desplaza; cada cuarta curva, más viva.
     Los dibujos con nombre se apagan en este dispositivo con localStorage calma-fondos = "no" (vuelve el plasma;
     en las cartas, nada). */
  const RAMPA = " .·:-=+*#%@";
  const ondas = [];   // {x, y, t0}: una onda que sale de donde has marcado algo (coordenadas de la ventana)
  function onda(x, y) { if (!quieto()) ondas.push({x, y, t0: performance.now()}); }
  const fondosApagados = () => { try { return localStorage.getItem("calma-fondos") === "no"; } catch { return false; } };
  // ruido de valor suave, para el relieve de las curvas
  const hash = (i, j) => { let h = Math.imul(i, 374761393) + Math.imul(j, 668265263) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296; };
  const ruido = (x, y) => { const i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j, u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
    const a = hash(i, j), b = hash(i + 1, j), c = hash(i, j + 1), d = hash(i + 1, j + 1);
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v; };
  const relieve = (x, y) => ruido(x, y) * .62 + ruido(x * 2.03 + 1.7, y * 2.03 + 9.2) * .28 + ruido(x * 4.1 + 3.1, y * 4.1 + 4.7) * .1;
  let px = -9999, py = -9999, toque = performance.now(), calla = performance.now() + 900;   // calla: hasta cuándo no repintar
  const VIDA = 1.6, VELOCIDAD = 380, ANCHO = 70;   // la onda: segundos, px/s y grosor del frente

  function fondo(host) {
    const pagina = host === document.body;
    let modo = host.dataset.fondo || "";
    if (modo && fondosApagados()) { if (!pagina) return; modo = ""; }
    if (modo && modo !== "plano" && modo !== "curvas") modo = "";
    const cv = Object.assign(document.createElement("canvas"), pagina ? {id: "c-fondo"} : {className: "c-fondo-carta"});
    cv.setAttribute("aria-hidden", "true");
    host.prepend(cv);
    const cx = cv.getContext("2d");
    let W, H, cw, ch, cols, filas, tinta, vivo, ultimo = 0, pedido = false, visible = true, F = null, ox = 0, oy = 0;
    const libre = ms => ms >= calla && !ocupado();
    const medir = () => {
      const r = Math.min(devicePixelRatio || 1, 2), C = innerWidth < 600 ? 12 : 14;
      W = pagina ? innerWidth : host.clientWidth; H = pagina ? innerHeight : host.clientHeight;
      cv.width = Math.max(1, W * r); cv.height = Math.max(1, H * r);
      cx.setTransform(r, 0, 0, r, 0, 0);
      cx.font = `${C}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
      cx.textBaseline = "top";
      cw = cx.measureText("M").width; ch = C * 1.25;
      cols = Math.ceil(W / cw) + 1; filas = Math.ceil(H / ch) + 1;
      F = modo === "curvas" ? new Float32Array((cols + 2) * (filas + 2)) : null;
      const css = getComputedStyle(document.documentElement);
      tinta = css.getPropertyValue("--ascii").trim(); vivo = css.getPropertyValue("--ascii-vivo").trim();
    };
    // el dedo y las ondas en una celda: d = distancia al dedo, ola = cuánto frente de onda pasa por ella
    const efectos = (x, y, ms) => {
      const cxp = x * cw + ox, cyp = y * ch + oy, d = Math.hypot(cxp - px, cyp - py);
      let ola = 0;
      for (const o of ondas) {
        const edad = (ms - o.t0) / 1000, k = Math.abs(Math.hypot(cxp - o.x, cyp - o.y) - edad * VELOCIDAD);
        if (k < ANCHO) ola += (1 - k / ANCHO) * (1 - edad / VIDA);
      }
      return [d, ola];
    };
    const R = RAMPA.length - 1;

    const plasma = (t, ms) => {
      for (let y = 0; y < filas; y++) {
        let fila = "", fuerte = "";
        for (let x = 0; x < cols; x++) {
          const v = Math.sin(x * .13 + t) + Math.sin(y * .19 - t * .8) + Math.sin((x + y) * .07 + t * .5)
                  + Math.sin(Math.hypot(x - cols * .7, y - filas * .25) * .16 - t * 1.2);   // -4..4
          let n = (v + 4) / 8;
          const [d, ola] = efectos(x, y, ms);
          if (d < 160) n += (1 - d / 160) * .55;   // el dedo aviva lo que tiene alrededor
          n += ola * .9;
          const i = Math.max(0, Math.min(R, Math.floor(n ** 1.25 * (R + 1))));   // toda la rampa, algo más de huecos
          fila += RAMPA[i];
          fuerte += i >= R - 1 || ola > .3 || d < 90 && i > 2 ? RAMPA[i] : " ";
        }
        cx.fillStyle = tinta; cx.fillText(fila, 0, y * ch);
        cx.fillStyle = vivo; cx.fillText(fuerte, 0, y * ch);
      }
    };

    // cuadros grandes de 8 columnas × 4 filas (~56 × 60 px) y un punto en cada cuadro pequeño (4 × 2)
    const plano = (t, ms) => {
      for (let y = 0; y < filas; y++) {
        let fila = "", fuerte = "";
        for (let x = 0; x < cols; x++) {
          const v = x % 8 === 0, h = y % 4 === 0;
          let c = v && h ? "+" : v ? "|" : h ? "-" : x % 4 === 0 && y % 2 === 0 ? "·" : " ";
          const [d, ola] = efectos(x, y, ms);
          const brillo = Math.sin(x * .05 - y * .11 + t * .9) > .985 - (h || v ? .03 : 0);   // una franja que barre la rejilla
          if (c === " " && ola > .25) c = RAMPA[Math.min(R, 2 + Math.floor(ola * 5))];
          else if (c === " " && d < 70) c = "·";
          fila += c;
          fuerte += c !== " " && (ola > .25 || d < 110 || brillo && c !== "·") ? c : " ";
        }
        cx.fillStyle = tinta; cx.fillText(fila, 0, y * ch);
        cx.fillStyle = vivo; cx.fillText(fuerte, 0, y * ch);
      }
    };

    // el relieve en cada celda (con una de margen para los vecinos); una curva donde cambia de nivel
    const NIVELES = 10, ESCALA = 210;   // px por unidad de ruido: igual en una carta que en la página
    const curvas = (t, ms) => {
      const A = cols + 2;
      for (let y = -1; y <= filas; y++) for (let x = -1; x <= cols; x++) {
        const xp = x * cw + ox, yp = y * ch + oy;
        let v = relieve(xp / ESCALA + t * .06, yp / ESCALA + t * .045) * NIVELES;
        const d = Math.hypot(xp - px, yp - py);
        if (d < 150) v += (1 - d / 150) ** 2 * 1.6;   // el dedo levanta una colina: las curvas lo rodean
        F[(y + 1) * A + x + 1] = v;
      }
      for (let y = 0; y < filas; y++) {
        let fila = "", fuerte = "";
        for (let x = 0; x < cols; x++) {
          const k = (y + 1) * A + x + 1, v = F[k], nivel = Math.round(v);
          const [, ola] = efectos(x, y, ms);
          let c = " ", viva = false;
          // la curva pasa por esta celda si el nivel entero más cercano queda a menos de media celda (medida a lo
          // largo de la pendiente, que es por donde cruza): así sale de un carácter de grueso, sin dobles
          const gx = (F[k + 1] - F[k - 1]) / (2 * cw), gy = (F[k + A] - F[k - A]) / (2 * ch), g = Math.hypot(gx, gy);
          const e = Math.abs(gx) * cw + Math.abs(gy) * ch;   // cuántos niveles cruza una celda
          const paso = e > .7 ? 4 : e > .35 ? 2 : 1;            // en lo empinado, como en los mapas, solo una de cada 2 o 4
          if (g > 1e-6 && Math.abs(v - nivel) < e / 2 && nivel % paso === 0) {
            const ax = Math.abs(gx), ay = Math.abs(gy);   // la curva va perpendicular a la pendiente
            c = ax > 2.2 * ay ? "|" : ay > 2.2 * ax ? "-" : gx * gy > 0 ? "/" : "\\";
            viva = nivel % 4 === 0;
          }
          if (ola > .3) { if (c === " ") c = RAMPA[Math.min(R, 2 + Math.floor(ola * 4))]; viva = true; }
          fila += c; fuerte += viva ? c : " ";
        }
        cx.fillStyle = tinta; cx.fillText(fila, 0, y * ch);
        cx.fillStyle = vivo; cx.fillText(fuerte, 0, y * ch);
      }
    };

    const dibujo = modo === "plano" ? plano : modo === "curvas" ? curvas : plasma;
    const pinta = ms => {
      while (ondas.length && (ms - ondas[0].t0) / 1000 > VIDA) ondas.shift();
      if (!pagina) { const r = host.getBoundingClientRect(); ox = r.left; oy = r.top; }
      cx.clearRect(0, 0, W, H);
      dibujo(ms / 1000 * .35, ms);
    };
    const bucle = ms => {
      if (document.visibilityState !== "visible") { pedido = false; return; }
      const cada = ondas.length ? 33 : ms - toque > 8000 ? 166 : 83;   // con onda, más fluido; sin tocar nada, más calma
      if (visible && ms - ultimo > cada && (ondas.length || libre(ms))) { ultimo = ms; pinta(ms); }
      requestAnimationFrame(bucle);
    };
    const arranca = () => { if (!pedido && !quieto()) { pedido = true; requestAnimationFrame(bucle); } };
    medir();
    pinta(performance.now());
    arranca();
    let tm;
    const otraVez = () => { clearTimeout(tm); tm = setTimeout(() => { medir(); pinta(performance.now()); }, 120); };
    addEventListener("calma-tema", otraVez);   // cambió la apariencia: otros colores para los caracteres
    if (pagina) addEventListener("resize", otraVez);
    else {
      new ResizeObserver(otraVez).observe(host);   // la carta crece cuando llegan sus datos
      new IntersectionObserver(es => { visible = es[0].isIntersecting; }).observe(host);
    }
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { medir(); pinta(performance.now()); });
    document.addEventListener("visibilitychange", arranca);
  }
  function fondos() {
    addEventListener("pointermove", e => { px = e.clientX; py = e.clientY; toque = performance.now(); }, {passive: true});
    addEventListener("pointerdown", () => { toque = performance.now(); }, {passive: true});
    // en captura: también el scroll de dentro de una carta o una hoja
    addEventListener("scroll", () => { calla = toque = performance.now(); calla += 250; }, {passive: true, capture: true});
    addEventListener("pointerup", () => setTimeout(() => { px = py = -9999; }, 600));
    if (tema && tema.intensidad === 0) return;   // Apariencia → Fondo: apagado
    fondo(document.body);
    document.querySelectorAll("[data-fondo]:not(body)").forEach(fondo);
  }

  /* ?medir=1 (hasta ?medir=0): arriba a la izquierda, fotogramas por segundo, tirones (fotogramas de más de
     50 ms desde que abriste la página) y cuánto tardó en estar lista. Para medir en el iPhone sin un Mac. */
  try { const m = new URLSearchParams(location.search).get("medir"); if (m) localStorage.setItem("calma-medir", m); } catch {}
  function medidor() {
    try { if (localStorage.getItem("calma-medir") !== "1") return; } catch { return; }
    const d = document.createElement("div");
    d.style.cssText = "position:fixed;left:6px;top:calc(env(safe-area-inset-top,0px) + 4px);z-index:999;pointer-events:none;" +
                      "font:600 11px ui-monospace,monospace;background:rgba(0,0,0,.7);color:#CDE77F;padding:3px 7px;border-radius:6px";
    document.body.append(d);
    let n = 0, tirones = 0, antes = performance.now(), t0 = antes;
    document.addEventListener("visibilitychange", () => { antes = t0 = performance.now(); n = 0; });
    const vuelta = ahora => {
      n++;
      if (ahora - antes > 50) tirones++;
      antes = ahora;
      if (ahora - t0 >= 1000) {
        const nav = performance.getEntriesByType("navigation")[0];
        d.textContent = `${Math.round(n * 1000 / (ahora - t0))} fps · ${tirones} tirones` + (nav ? ` · lista en ${Math.round(nav.domContentLoadedEventEnd)} ms` : "");
        n = 0;
        t0 = ahora;
      }
      requestAnimationFrame(vuelta);
    };
    requestAnimationFrame(vuelta);
  }
  /* ---------- Disposición: el orden y lo escondido de las secciones de cada pantalla ----------
     Las secciones son las cartas de la página (section, article, .c-carta, [data-mod]…) que comparten padre.
     Su id es data-bloque, o sale de su título. Se guarda por pantalla en /api/apariencia (y en localStorage).
     Para editar: ?editar=1, mantener pulsado el título de la página, o calma.editaPantalla(). */
  const SEL_BLOQUE = "section, article, .c-carta, [data-mod], .escena3d, [data-bloque]";
  const pantalla = () => {
    const app = location.hostname.split(".")[0];
    let p = location.pathname.replace(/^\/+|\.html$/g, "");
    if (app === "todo" || app === "localhost" || /^\d/.test(app)) {
      if (p === "" || p === "hoy") p = "hoy"; else if (p === "index" || p === "habitos") p = "habitos";
      return p;
    }
    return (app + "-" + (p || "inicio")).replace(/[^a-z0-9-]/g, "").slice(0, 40);
  };
  const slug = t => (t || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 32);
  function grupos() {
    const app = document.querySelector(".app") || document.body;
    const padres = new Map();
    for (const el of app.querySelectorAll(SEL_BLOQUE)) {
      if (el.closest("header.top, nav, .c-hoja, dialog") || el.parentElement.closest(SEL_BLOQUE)) continue;
      const l = padres.get(el.parentElement) || [];
      l.push(el); padres.set(el.parentElement, l);
    }
    const vistos = new Set(), fuera = [];
    for (const [padre, els] of padres) {
      if (els.length < 2) continue;
      for (const el of els) {
        if (!el.dataset.bloque) {
          const titulo = el.getAttribute("aria-label") || el.querySelector("h2, h3, .c-eti, small")?.textContent || el.dataset.mod || el.id || "bloque";
          let id = slug(titulo) || "bloque", n = 2;
          while (vistos.has(id)) id = slug(titulo) + "-" + n++;
          el.dataset.bloque = id;
        }
        vistos.add(el.dataset.bloque);
        el.dataset.nombre = el.dataset.nombre || (el.getAttribute("aria-label") || el.querySelector("h2, h3, .c-eti")?.textContent || el.dataset.bloque).trim().replace(/\s+/g, " ").slice(0, 40);
      }
      fuera.push({padre, els});
    }
    return fuera;
  }
  function ordena(gs, d) {
    const orden = d?.orden || [], ocultos = new Set(d?.ocultos || []);
    for (const {els} of gs) {
      const pos = id => { const i = orden.indexOf(id); return i < 0 ? 1e6 : i; };
      const nuevo = els.map((el, i) => ({el, i})).sort((a, b) => (pos(a.el.dataset.bloque) - pos(b.el.dataset.bloque)) || (a.i - b.i)).map(x => x.el);
      const huecos = els.map(el => { const m = document.createComment(""); el.before(m); return m; });
      nuevo.forEach((el, i) => huecos[i].replaceWith(el));
      els.splice(0, els.length, ...nuevo);
      for (const el of els) el.classList.toggle("c-oculto", ocultos.has(el.dataset.bloque));
    }
  }
  let todaDisposicion = {};
  async function disposicion() {
    todaDisposicion = await disposicionLista;
    const gs = grupos();
    ordena(gs, todaDisposicion[pantalla()]);
    if (new URLSearchParams(location.search).has("editar")) editaPantalla();
    // mantener pulsado el título (sin que iOS seleccione el texto ni saque su menú: .c-titulo-editable en calma.css)
    const h1 = document.querySelector(".app h1, h1");
    let tm;
    h1?.classList.add("c-titulo-editable");
    h1?.addEventListener("contextmenu", e => e.preventDefault());
    h1?.addEventListener("pointerdown", () => { tm = setTimeout(editaPantalla, 550); });
    for (const ev of ["pointerup", "pointerleave", "pointercancel", "pointermove"]) h1?.addEventListener(ev, e => { if (ev !== "pointermove" || e.movementY > 4) clearTimeout(tm); });
  }
  async function guardaDisposicion(p, d) {
    todaDisposicion = {...todaDisposicion, [p]: d};
    if (!d) delete todaDisposicion[p];
    ponLocal("calma-disposicion", todaDisposicion);
    try {
      const r = await fetch("/api/apariencia", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"},
                                                body: JSON.stringify({disposicion: todaDisposicion})});
      return r.ok;
    } catch { return false; }
  }
  function editaPantalla() {
    if (raiz.classList.contains("c-editando")) return;
    const gs = grupos();
    if (!gs.length) return;
    vibra();
    raiz.classList.add("c-editando");
    const barra = document.createElement("div");
    barra.className = "c-edita-barra";
    barra.innerHTML = '<span>Ordena y esconde secciones</span><button type="button" class="c-btn mini" data-e="reset">Restablecer</button><button type="button" class="c-btn mini pri" data-e="listo">Listo</button>';
    document.body.append(barra);
    const herramientas = [];
    for (const {els} of gs) for (const el of els) {
      const t = document.createElement("div");
      t.className = "c-edita-bloque";
      t.innerHTML = '<button type="button" data-e="sube" aria-label="Subir"><svg viewBox="0 0 24 24"><path d="M6 15l6-6 6 6"/></svg></button>'
        + '<button type="button" data-e="baja" aria-label="Bajar"><svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg></button>'
        + '<button type="button" data-e="ver" aria-label="Mostrar u ocultar"><svg viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg></button>';
      t.addEventListener("click", e => {
        const b = e.target.closest("button"); if (!b) return;
        e.preventDefault(); e.stopPropagation();
        const g = gs.find(x => x.els.includes(el)), i = g.els.indexOf(el);
        if (b.dataset.e === "ver") el.classList.toggle("c-oculto");
        else {
          const j = b.dataset.e === "sube" ? i - 1 : i + 1;
          if (j < 0 || j >= g.els.length) return;
          const otro = g.els[j];
          transicion(() => { if (j < i) otro.before(el); else otro.after(el); });
          g.els.splice(i, 1); g.els.splice(j, 0, el);
        }
        vibra();
      });
      el.append(t); herramientas.push(t);
    }
    const sal = () => { herramientas.forEach(t => t.remove()); barra.remove(); raiz.classList.remove("c-editando"); };
    barra.addEventListener("click", async e => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.e === "reset") { sal(); await guardaDisposicion(pantalla(), null); location.replace(location.pathname); return; }
      const todos = gs.flatMap(g => g.els);
      const d = {orden: todos.map(x => x.dataset.bloque), ocultos: todos.filter(x => x.classList.contains("c-oculto")).map(x => x.dataset.bloque)};
      sal();
      const ok = await guardaDisposicion(pantalla(), d);
      if (!ok) console.warn("disposición guardada solo en este dispositivo");
      if (location.search.includes("editar")) history.replaceState(null, "", location.pathname);
    });
  }

  /* dentro de Tom: un micro en la cabecera abre «Hablar con Tom» (el modo voz nativo) */
  function botonVoz() {
    if (!window.HoyApp || !window.webkit?.messageHandlers?.hoy) return;
    const cab = document.querySelector("header.top");
    if (!cab || cab.querySelector(".c-voz")) return;
    const b = document.createElement("button");
    b.type = "button"; b.className = "c-voz"; b.setAttribute("aria-label", "Hablar con Tom");
    b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
    b.addEventListener("click", () => { vibra(); try { window.webkit.messageHandlers.hoy.postMessage({accion: "voz"}); } catch {} });
    cab.append(b);
  }

  const listo = () => { menu(); islaReal(); fondos(); medidor(); disposicion(); botonVoz(); };
  document.readyState === "loading" ? addEventListener("DOMContentLoaded", listo) : listo();

  /* Al irse a otra página: el contenido baja un poco mientras se desvanece (.c-saliendo en calma.css)
     y luego se navega; la siguiente entra con anima.entrada(). El fondo y el menú se quedan quietos.
     Desde JS, además, la app instalada del iPhone no se sale al navegador (con un enlace normal sí). */
  function vete(url, espera = 130) {
    if (!quieto() && !entrePaginas()) document.documentElement.classList.add("c-saliendo");
    setTimeout(() => { location.href = url; }, quieto() ? 0 : espera);
  }
  /* Transición entre páginas (View Transitions entre documentos: Safari 18.2, Chrome 126). La pide cada página
     con <html data-vt> y @view-transition en su <style>; calma.css le da nombre a la cabecera y a la barra.
     Entonces no hay salida propia (.c-saliendo): la foto de la página vieja tiene que salir entera. */
  const entrePaginas = () => !quieto() && "CSSViewTransitionRule" in window && document.documentElement.hasAttribute("data-vt");
  addEventListener("pagereveal", e => {
    if (!e.viewTransition) return;
    if (quieto()) return e.viewTransition.skipTransition();
    // la cabecera llega volando de la otra página: se ve desde el principio aunque el resto espere a los datos
    document.documentElement.classList.add("c-vt");
  });
  // al volver con «atrás», el navegador puede devolver la página tal cual se fue: desvanecida
  addEventListener("pageshow", e => { if (e.persisted) document.documentElement.classList.remove("c-saliendo"); });
  document.addEventListener("click", e => {
    const a = e.target.closest?.("a[href]");
    if (!a || e.defaultPrevented || e.button || a.target || a.hasAttribute("download") || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin) return;   // obsidian://, webs de fuera: como siempre
    if (u.pathname === location.pathname && u.search === location.search) return;   // #ancla de la misma página
    e.preventDefault();
    vete(u.href, entrePaginas() ? 0 : 130);
  });

  /* Vibración. Safari no deja vibrar a las webs, pero al cambiar un interruptor nativo (iOS 17.4+)
     el iPhone da un toque: hay uno escondido que se «pulsa» dentro del mismo gesto. En Android, vibrate(). */
  let interruptor;
  function vibra() {
    if (navigator.vibrate) { navigator.vibrate(10); return; }
    if (!interruptor) {
      interruptor = document.createElement("label");
      interruptor.setAttribute("aria-hidden", "true");
      interruptor.style.cssText = "position:fixed;left:-200px;top:0;opacity:0;pointer-events:none";
      interruptor.innerHTML = '<input type="checkbox" switch tabindex="-1">';
      document.body.append(interruptor);
    }
    interruptor.click();
  }
  // marcar algo (un hábito, una tarea) vibra y lanza una onda en el fondo; navegar o guardar, solo vibra
  document.addEventListener("click", e => {
    const t = e.target.closest?.(".fila, .bx, .c-dock a, .c-h-pie button, .c-pil, .c-cal-rej button, .mas-tarea, [data-toque]");
    if (!t || t.disabled) return;
    vibra();
    if (t.matches(".fila, .bx")) onda(e.clientX, e.clientY);
  }, true);

  /* borde que sigue al dedo (.c-foco en calma.css) */
  addEventListener("pointermove", e => {
    const c = e.target.closest?.(".c-foco");
    if (!c) return;
    const r = c.getBoundingClientRect();
    c.style.setProperty("--x", e.clientX - r.left + "px");
    c.style.setProperty("--y", e.clientY - r.top + "px");
  }, {passive: true});

  /* Vúmetro de aguja (aparato hardware): frac 0-1 es el objetivo; la zona roja, pasarse. Devuelve el HTML, para
     meterlo donde la página quiera (Hoy, Salud, Gastos). Con «reducir movimiento» la aguja no se balancea. */
  function vu(frac, valor, que, etiqueta = "VU") {
    const r = 62, cx = 80, cy = 80, rad = g => g * Math.PI / 180, x = g => (cx + r * Math.sin(rad(g))).toFixed(1), y = g => (cy - r * Math.cos(rad(g))).toFixed(1);
    const a = -50 + Math.max(0, Math.min(1.25, Number(frac) || 0)) * 80;   // 0 → -50°, objetivo → +30°, el resto, rojo
    const marcas = Array.from({length: 11}, (_, i) => {
      const g = -50 + i * 10, r2 = i % 5 ? 56 : 52;
      return `<line x1="${x(g)}" y1="${y(g)}" x2="${(cx + r2 * Math.sin(rad(g))).toFixed(1)}" y2="${(cy - r2 * Math.cos(rad(g))).toFixed(1)}" stroke="${g > 30 ? "#E2412F" : "currentColor"}" stroke-width="${i % 5 ? 1 : 2}"/>`;
    }).join("");
    return `<div class="hw-ambar hw-vu" role="img" aria-label="${que}: ${valor}"><svg viewBox="0 0 160 86" aria-hidden="true">
      <path d="M${x(-50)} ${y(-50)} A${r} ${r} 0 0 1 ${x(30)} ${y(30)}" fill="none" stroke="currentColor" stroke-opacity=".5"/>
      <path d="M${x(30)} ${y(30)} A${r} ${r} 0 0 1 ${x(50)} ${y(50)}" fill="none" stroke="#E2412F" stroke-width="3"/>${marcas}
      <text x="80" y="46" text-anchor="middle" font-size="14" fill="currentColor" opacity=".7" font-family="VT323, monospace">${etiqueta}</text>
      <g class="hw-aguja" style="transform-origin: 80px 82px; transform: rotate(${a.toFixed(1)}deg)"><line x1="80" y1="82" x2="80" y2="18" stroke="#FF3D2A" stroke-width="1.6"/></g>
      <circle cx="80" cy="82" r="5" fill="#222" stroke="currentColor" stroke-opacity=".4"/></svg>
      <div class="hw-vu-valor">${valor}</div><div class="hw-vu-que">${que}</div></div>`;
  }
  /* Arco de sol (aparato solar): medio círculo que se llena hasta el objetivo (frac 1). Devuelve el HTML. */
  function arco(frac, valor, que, color = "var(--acento)") {
    const L = Math.PI * 40, p = Math.max(0, Math.min(1, Number(frac) || 0));
    return `<div class="sol-arco" role="img" aria-label="${que}: ${valor}"><svg viewBox="0 0 100 56" aria-hidden="true">
      <path d="M10 50a40 40 0 0 1 80 0" fill="none" stroke="var(--carta-2)" stroke-width="9" stroke-linecap="round"/>
      <path class="sol-arco-lleno" d="M10 50a40 40 0 0 1 80 0" fill="none" stroke="${color}" stroke-width="9" stroke-linecap="round" stroke-dasharray="${(L * p).toFixed(1)} ${L.toFixed(1)}"/></svg>
      <b>${valor}</b><small>${que}</small></div>`;
  }
  /* Cota (aparato plano): una medida de plano con el rayado hasta el valor; frac 1 = el objetivo. */
  function cota(frac, valor, que) {
    const f = Math.max(0, Number(frac) || 0);
    return `<div class="pl-cota" role="img" aria-label="${que}: ${valor}"><div class="pl-que"><span>${que}</span><b>${valor}</b></div>
      <div class="pl-regla" aria-hidden="true"><i class="pl-lleno${f > 1 ? " pasado" : ""}" style="--p:${(Math.min(1, f) * 100).toFixed(1)}%"></i></div></div>`;
  }
  /* Medallón (aparato conserje): aro dorado que se cierra hasta el objetivo, con la cifra dentro. */
  function medalla(frac, valor, que) {
    const L = 2 * Math.PI * 40, p = Math.max(0, Math.min(1, Number(frac) || 0));
    return `<div class="cj-medalla" role="img" aria-label="${que}: ${valor}"><svg viewBox="0 0 100 100" aria-hidden="true">
      <circle cx="50" cy="50" r="47" fill="none" stroke="var(--cj-granate)" stroke-width="1.2"/>
      <circle cx="50" cy="50" r="40" fill="none" stroke="color-mix(in srgb, var(--cj-oro) 25%, transparent)" stroke-width="6"/>
      <circle class="cj-aro" cx="50" cy="50" r="40" fill="none" stroke="var(--cj-oro)" stroke-width="6" stroke-dasharray="${(L * p).toFixed(1)} ${L.toFixed(1)}" transform="rotate(-90 50 50)"/>
      <circle cx="50" cy="50" r="33" fill="none" stroke="var(--cj-granate)" stroke-width=".8" stroke-dasharray="1.5 2.5"/>
      <text class="cj-cifra" x="50" y="56" text-anchor="middle">${valor}</text></svg><small>${que}</small></div>`;
  }
  const aparato = () => raiz.dataset.aparato || "calma";

  return {transicion, cuenta, fiesta, vibra, onda, perfil, ponPerfil, saludo, ocupado, entrePaginas, vu, arco, cota, medalla, aparato,
          ponApariencia, pideCatalogo, calculaTema, genera, aOklch, deOklch, editaPantalla, pantalla, grupos, guardaDisposicion,
          tema: () => tema, disposicionGuardada: () => disposicionLista};
})();
