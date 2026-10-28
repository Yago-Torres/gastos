/* Calma — movimiento común de las apps (fuente: ~/estilo/calma.js, copiada por aplica.sh).
   Todo respeta "reducir movimiento" del sistema: si está activo, no se anima nada. */
const calma = (() => {
  const quieto = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

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
  function transicion(fn) {
    // con la pestaña oculta Chrome aborta la transición (InvalidStateError) y fn no llega a pintar
    if (quieto() || !document.startViewTransition || document.visibilityState !== "visible") return fn();
    document.startViewTransition(fn).ready.catch(() => {});
  }

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

  /* El menú de todo (en todas sus páginas, también en comida.html y gastos.html) se rehace como la
     barra de abajo: todas las secciones, siempre en el mismo sitio, y la actual es una gota que sale
     de la barra. Al tocar otra, la gota se desliza hasta ella y luego se navega.
     Solo toca el nav que enlaza a pendientes, entreno o carrera. */
  const I = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
  const MENU = [
    ["/", "Hoy", I('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>')],
    ["/habitos.html", "Hábitos", I('<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.5"/>')],
    ["/pendientes.html", "Pendientes", I('<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>')],
    ["/entreno.html", "Entreno", I('<path d="M6.5 6.5v11M17.5 6.5v11M3.5 9v6M20.5 9v6M6.5 12h11"/>')],
    ["/sueno.html", "Sueño", I('<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>')],
    ["/comida.html", "Comida", I('<path d="M3 11h18a9 9 0 0 1-18 0zM8 7c0-1.5 1-2 1-3.5M12 7c0-1.5 1-2 1-3.5M16 7c0-1.5 1-2 1-3.5"/>')],
    ["/gastos.html", "Gastos", I('<rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10h18M16 15h2"/>')],
  ];
  function menu() {
    const nav = [...document.querySelectorAll("nav")].find(n => n.querySelector('a[href="/pendientes.html"], a[href="/entreno.html"], a[href="/carrera.html"]'));
    if (!nav) return;
    // Hoy es la portada (/, y también /hoy.html); Hábitos vive en /habitos.html (y /index.html)
    const aqui = {"/hoy.html": "/", "/index.html": "/habitos.html", "/carrera.html": "/entreno.html"}[location.pathname] || location.pathname;
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
    nav.replaceChildren(goo, ...MENU.map(([href, nombre, icono]) => {
      const a = Object.assign(document.createElement("a"), {href, innerHTML: `${icono}<span>${nombre}</span>`});
      if (href === aqui) a.setAttribute("aria-current", "page");
      return a;
    }));
    document.body.append(nav);   // fuera de la cabecera: el mismo sitio en todas las páginas
    const actual = () => nav.querySelector('a[aria-current="page"]');
    const pon = (a, animada) => {
      gota.style.transition = animada ? "" : "none";
      gota.style.transform = `translateX(${a.offsetLeft + a.offsetWidth / 2 - 26}px)`;
    };
    const coloca = () => { gota.hidden = !actual(); if (actual()) pon(actual(), false); };
    coloca();
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
      vete(a.href, 320);   // la gota se desliza mientras la página se va
    });
  }
  /* App instalada en un iPhone con isla dinámica (barra de estado de 51 px o más): los avisos salen de ella */
  function islaReal() {
    const sonda = Object.assign(document.createElement("div"), {style: "position:fixed;top:0;height:env(safe-area-inset-top,0px);visibility:hidden"});
    document.body.append(sonda);
    if (navigator.standalone && sonda.offsetHeight >= 51) document.documentElement.classList.add("c-isla-real");
    sonda.remove();
  }
  /* Fondo: un «shader» de caracteres ASCII. Un plasma de senos decide en cada celda qué carácter
     toca (de « » a «@»); se mueve despacio y se aviva alrededor del dedo. Canvas 2D, una llamada
     por fila, a 12 fotogramas por segundo; parado con la pestaña oculta y quieto con «reducir movimiento». */
  const RAMPA = " .·:-=+*#%@";
  const ondas = [];   // {x, y, t0}: una onda que sale de donde has marcado algo
  function onda(x, y) { if (!quieto()) ondas.push({x, y, t0: performance.now()}); }
  function fondo() {
    const cv = Object.assign(document.createElement("canvas"), {id: "c-fondo"});
    cv.setAttribute("aria-hidden", "true");
    document.body.prepend(cv);
    const cx = cv.getContext("2d");
    let W, H, cw, ch, cols, filas, tinta, vivo, px = -9999, py = -9999, ultimo = 0, pedido = false;
    const medir = () => {
      const r = Math.min(devicePixelRatio || 1, 2), C = innerWidth < 600 ? 12 : 14;
      W = innerWidth; H = innerHeight;
      cv.width = W * r; cv.height = H * r;
      cx.setTransform(r, 0, 0, r, 0, 0);
      cx.font = `${C}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
      cx.textBaseline = "top";
      cw = cx.measureText("M").width; ch = C * 1.25;
      cols = Math.ceil(W / cw) + 1; filas = Math.ceil(H / ch) + 1;
      const css = getComputedStyle(document.documentElement);
      tinta = css.getPropertyValue("--ascii").trim(); vivo = css.getPropertyValue("--ascii-vivo").trim();
    };
    const VIDA = 1.6, VELOCIDAD = 380, ANCHO = 70;   // la onda: segundos, px/s y grosor del frente
    const pinta = ms => {
      const t = ms / 1000 * .35, R = RAMPA.length - 1;
      while (ondas.length && (ms - ondas[0].t0) / 1000 > VIDA) ondas.shift();
      cx.clearRect(0, 0, W, H);
      for (let y = 0; y < filas; y++) {
        let fila = "", fuerte = "";
        for (let x = 0; x < cols; x++) {
          const v = Math.sin(x * .13 + t) + Math.sin(y * .19 - t * .8) + Math.sin((x + y) * .07 + t * .5)
                  + Math.sin(Math.hypot(x - cols * .7, y - filas * .25) * .16 - t * 1.2);   // -4..4
          let n = (v + 4) / 8, ola = 0;
          const d = Math.hypot(x * cw - px, y * ch - py);
          if (d < 160) n += (1 - d / 160) * .55;   // el dedo aviva lo que tiene alrededor
          for (const o of ondas) {                  // el frente de cada onda, que se apaga al alejarse
            const edad = (ms - o.t0) / 1000, k = Math.abs(Math.hypot(x * cw - o.x, y * ch - o.y) - edad * VELOCIDAD);
            if (k < ANCHO) ola += (1 - k / ANCHO) * (1 - edad / VIDA);
          }
          n += ola * .9;
          const i = Math.max(0, Math.min(R, Math.floor(n ** 1.25 * (R + 1))));   // toda la rampa, algo más de huecos
          fila += RAMPA[i];
          fuerte += i >= R - 1 || ola > .3 || d < 90 && i > 2 ? RAMPA[i] : " ";
        }
        cx.fillStyle = tinta; cx.fillText(fila, 0, y * ch);
        cx.fillStyle = vivo; cx.fillText(fuerte, 0, y * ch);
      }
    };
    const bucle = ms => {
      if (document.visibilityState !== "visible") { pedido = false; return; }
      if (ms - ultimo > (ondas.length ? 33 : 83)) { ultimo = ms; pinta(ms); }   // con onda, más fluido
      requestAnimationFrame(bucle);
    };
    const arranca = () => { if (!pedido && !quieto()) { pedido = true; requestAnimationFrame(bucle); } };
    medir();
    pinta(performance.now());
    arranca();
    let tm;
    addEventListener("resize", () => { clearTimeout(tm); tm = setTimeout(() => { medir(); pinta(performance.now()); }, 120); });
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { medir(); pinta(performance.now()); });
    document.addEventListener("visibilitychange", arranca);
    addEventListener("pointermove", e => { px = e.clientX; py = e.clientY; }, {passive: true});
    addEventListener("pointerup", () => setTimeout(() => { px = py = -9999; }, 600));
  }

  const listo = () => { menu(); islaReal(); fondo(); };
  document.readyState === "loading" ? addEventListener("DOMContentLoaded", listo) : listo();

  /* Al irse a otra página: el contenido baja un poco mientras se desvanece (.c-saliendo en calma.css)
     y luego se navega; la siguiente entra con anima.entrada(). El fondo y el menú se quedan quietos.
     Desde JS, además, la app instalada del iPhone no se sale al navegador (con un enlace normal sí). */
  function vete(url, espera = 230) {
    if (!quieto()) document.documentElement.classList.add("c-saliendo");
    setTimeout(() => { location.href = url; }, quieto() ? 0 : espera);
  }
  // al volver con «atrás», el navegador puede devolver la página tal cual se fue: desvanecida
  addEventListener("pageshow", e => { if (e.persisted) document.documentElement.classList.remove("c-saliendo"); });
  document.addEventListener("click", e => {
    const a = e.target.closest?.("a[href]");
    if (!a || e.defaultPrevented || e.button || a.target || a.hasAttribute("download") || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin) return;   // obsidian://, webs de fuera: como siempre
    if (u.pathname === location.pathname && u.search === location.search) return;   // #ancla de la misma página
    e.preventDefault();
    vete(u.href);
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

  return {transicion, cuenta, fiesta, vibra, onda};
})();
