/* Animaciones de adorno con anime.js, comunes a las apps (fuente: ~/estilo/anima.js, copiada
   por aplica.sh junto a anime-4.5.0.min.js). index.html de todo lleva además las suyas.
   Sin anime.js o con «reducir movimiento» no hace nada y las páginas funcionan igual. */
const anima = (() => {
  const mov = !!window.anime && !matchMedia("(prefers-reduced-motion: reduce)").matches;
  const CHECK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12.5l4 4 8-9"/></svg>';

  // Lo que se pinta por primera vez entra en cascada, de arriba abajo. Antes de nada se deja
  // invisible y abajo, en el mismo fotograma: si no, lo que espera su turno se ve un instante,
  // desaparece al empezar y vuelve a subir (el «flash»). También quita el velo de carga de calma.js.
  function entra(sel, paso = 40, desde = 0) {
    const els = [...document.querySelectorAll(sel)];
    if (mov && els.length) {
      els.forEach(e => { e.style.opacity = "0"; e.style.transform = "translateY(14px)"; });
      anime.animate(els, {y: [14, 0], opacity: [0, 1], delay: anime.stagger(paso, {start: desde}), duration: 420, ease: "outCubic"});
    }
    document.documentElement.classList.remove("c-cargando");
  }

  // La entrada de todas las páginas, igual en todas: el título letra a letra y las tarjetas en
  // cascada, al mismo ritmo. Cada página la llama una vez, cuando ya tiene sus datos pintados.
  function entrada() {
    const h1 = document.querySelector(".app h1");
    if (mov && h1 && !h1.dataset.entro) {
      h1.dataset.entro = "1";
      anime.animate(anime.splitText(h1, {chars: true}).chars,
        {y: ["60%", "0%"], opacity: [0, 1], delay: anime.stagger(12), duration: 420, ease: "outExpo"});
    }
    entra(".app .c-carta, .app .panel, .app .escena3d", 40, 40);
  }

  // hecho: el círculo se rellena y el check se dibuja, y la fila se pliega hacia la derecha.
  // Devuelve una promesa que se cumple al acabar (sin animación, enseguida).
  function hecha(fila, bx) {
    if (!mov) return Promise.resolve();
    if (bx) {
      bx.innerHTML = CHECK;
      bx.classList.add("ok");
      anime.animate(bx, {scale: [.6, 1], duration: 300, ease: "outBack(3)"});
      anime.animate(anime.svg.createDrawable(bx.querySelector("path")), {draw: ["0 0", "0 1"], duration: 240, ease: "outQuad"});
    }
    fila.style.overflow = "hidden";
    return anime.animate(fila, {x: [0, 28], opacity: [1, 0], height: [fila.offsetHeight, 0],
      paddingTop: 0, paddingBottom: 0, marginTop: 0, marginBottom: 0,
      delay: bx ? 340 : 0, duration: 320, ease: "inQuad"}).then(() => {});
  }

  // algo recién añadido o que se abre: aparece con un brinco
  function nueva(el) {
    if (mov && el) anime.animate(el, {scale: [.94, 1], opacity: [0, 1], duration: 520, ease: "outBack(2)"});
  }

  // un botón que se acaba de marcar da un saltito
  function salta(el) {
    if (mov && el) anime.animate(el, {scale: [.55, 1], duration: 340, ease: "outBack(3)"});
  }

  // barras de progreso (c-barra, con --p) que se llenan desde cero; al acabar vuelve a mandar --p
  function llena(sel, retardo = 200) {
    if (!mov) return;
    document.querySelectorAll(sel).forEach((b, i) => {
      const fin = getComputedStyle(b).getPropertyValue("--p").trim() || "0%";
      const barra = b.querySelector("i");
      if (barra) anime.animate(barra, {width: ["0%", fin], duration: 900, delay: retardo + i * 60, ease: "outExpo"})
        .then(() => { barra.style.width = ""; });
    });
  }

  // para Chart.js: las gráficas se dibujan solas, punto a punto, de izquierda a derecha
  const graficas = d => (mov ? {duration: 700, easing: "easeOutQuart",
    delay: c => c.type === "data" && c.mode === "default" ? d + c.dataIndex * 45 : 0} : false);

  return {mov, entra, entrada, hecha, nueva, salta, llena, graficas};
})();
