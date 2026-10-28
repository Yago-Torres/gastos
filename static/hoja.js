/* Hoja de cristal para una tarea: el texto, el día (tira de días y calendario) y la hora (dos ruedas).
   Común a las apps (fuente: ~/estilo/hoja.js, copiada por aplica.sh; estilos .c-hoja en calma.css).

     hoja.abre({titulo, texto, due, hora, alGuardar, alBorrar})
       texto: null = sin campo de texto (solo el cuándo); "" o algo = se edita también el texto.
       alGuardar({t, due, hora}) puede ser async; si devuelve false, la hoja se queda abierta.
       alBorrar(): opcional; con él sale la papelera (dos toques). Igual: false = no se cierra.
     hoja.etiqueta(due, hora) → "Hoy · 10:00", "viernes 30 oct", "Sin fecha"…              */
const hoja = (() => {
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const MESES_L = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  const DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
  const DIAS_L = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
  const ALTO = 42, MINS = [...Array(12)].map((_, i) => i * 5);
  const hoy = () => new Date().toLocaleDateString("sv");
  const fecha = s => new Date(s + "T12:00:00");
  const mas = (s, n) => { const d = fecha(s); d.setDate(d.getDate() + n); return d.toLocaleDateString("sv"); };
  const entre = (a, b) => Math.round((fecha(b) - fecha(a)) / 864e5);
  const corta = s => `${fecha(s).getDate()} ${MESES[fecha(s).getMonth()]}`;
  const largo = s => s ? `${DIAS_L[fecha(s).getDay()]} ${fecha(s).getDate()} ${MESES[fecha(s).getMonth()]}` : "";
  const etiqueta = (due, hora) => !due ? "Sin fecha"
    : (entre(hoy(), due) === 0 ? "Hoy" : entre(hoy(), due) === 1 ? "Mañana" : largo(due)) + (hora ? ` · ${hora}` : "");
  const el = (t, cls, txt) => { const e = document.createElement(t); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
  const H = {due: "", hora: "", mes: null, alGuardar: null, alBorrar: null};
  let $ = null, RH, RM, antes = null;

  function monta() {
    document.body.insertAdjacentHTML("beforeend", `
<div class="c-velo" id="c-velo"></div>
<section class="c-hoja" id="c-hoja" role="dialog" aria-modal="true" aria-labelledby="c-h-tit">
  <div class="c-h-cab"><h2 id="c-h-tit">Cuándo</h2><span id="c-h-resumen" aria-live="polite"></span></div>
  <input class="c-campo" id="c-h-texto" maxlength="200" aria-label="Qué tienes que hacer" placeholder="Llamar al dentista">
  <div class="c-h-eti">Día</div>
  <div class="c-dias" id="c-h-dias" role="group" aria-label="Día"></div>
  <div class="c-cal" id="c-h-cal" hidden>
    <div class="c-cal-cab"><button type="button" id="c-h-antes" aria-label="Mes anterior">‹</button><span id="c-h-mes"></span><button type="button" id="c-h-luego" aria-label="Mes siguiente">›</button></div>
    <div class="c-cal-rej" id="c-h-rej"></div>
  </div>
  <div class="c-h-eti">Hora <button type="button" class="c-btn mini" id="c-h-sinhora" aria-pressed="true">Sin hora</button></div>
  <div class="c-rueda apagada" id="c-h-rueda" aria-label="Hora del aviso">
    <div class="c-tambor" id="c-h-h" tabindex="0" aria-label="Horas"></div><b>:</b><div class="c-tambor" id="c-h-m" tabindex="0" aria-label="Minutos"></div>
  </div>
  <div class="c-h-pie">
    <button type="button" class="c-btn c-h-borrar" id="c-h-borrar" aria-label="Borrar la tarea" hidden><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg><span>¿Borrar?</span></button>
    <button type="button" class="c-btn" id="c-h-no">Cancelar</button><button type="button" class="c-btn pri" id="c-h-ok">Guardar</button>
  </div>
</section>`);
    $ = id => document.getElementById("c-h-" + id);
    $("antes").onclick = () => { H.mes = H.mes[1] ? [H.mes[0], H.mes[1] - 1] : [H.mes[0] - 1, 11]; pintaMes(); };
    $("luego").onclick = () => { H.mes = H.mes[1] < 11 ? [H.mes[0], H.mes[1] + 1] : [H.mes[0] + 1, 0]; pintaMes(); };
    RH = rueda($("h"), [...Array(24).keys()]);
    RM = rueda($("m"), MINS);
    $("sinhora").onclick = () => {
      if (H.hora) H.hora = "";
      else { lee(); if (!H.due) H.due = hoy(); }
      pinta();
    };
    // en el ordenador, también con las flechas
    [$("h"), $("m")].forEach(c => c.addEventListener("keydown", e => {
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
      e.preventDefault();
      c.scrollBy({top: (e.key === "ArrowDown" ? 1 : -1) * ALTO, behavior: "smooth"});
    }));
    document.getElementById("c-velo").onclick = cierra;
    $("no").onclick = cierra;
    addEventListener("keydown", e => e.key === "Escape" && document.getElementById("c-hoja").classList.contains("on") && cierra());
    // borrar: el primer toque pregunta (y a los 3 s se olvida), el segundo borra
    let olvida;
    $("borrar").onclick = async () => {
      const b = $("borrar");
      if (!b.classList.contains("seguro")) {
        b.classList.add("seguro");
        b.setAttribute("aria-label", "Confirmar: borrar la tarea");
        clearTimeout(olvida);
        olvida = setTimeout(() => b.classList.remove("seguro"), 3000);
        return;
      }
      clearTimeout(olvida);
      b.disabled = true;
      try { if (await H.alBorrar() !== false) cierra(); }
      finally { b.disabled = false; b.classList.remove("seguro"); }
    };
    $("ok").onclick = async () => {
      $("ok").disabled = true;
      try { if (await H.alGuardar({t: $("texto").value, due: H.due, hora: H.due ? H.hora : ""}) !== false) cierra(); }
      finally { $("ok").disabled = false; }
    };
  }

  function pinta() {
    const HOY = hoy();
    $("resumen").textContent = etiqueta(H.due, H.hora);
    // la tira: sin fecha, hoy, mañana y los 12 días siguientes; más allá, «otro día»
    const tira = [["", "Sin", "fecha"], ...[...Array(14)].map((_, i) => {
      const d = mas(HOY, i);
      return [d, i === 0 ? "Hoy" : i === 1 ? "Mañana" : DIAS[fecha(d).getDay()], String(fecha(d).getDate())];
    })];
    const lejos = H.due && (entre(HOY, H.due) < 0 || entre(HOY, H.due) > 13);
    const pils = tira.map(([d, arriba, abajo]) => {
      const b = el("button", "c-pil" + (d ? "" : " texto"));
      b.type = "button";
      b.append(el("small", null, arriba), el("b", null, abajo));
      b.setAttribute("aria-pressed", d === H.due);
      b.setAttribute("aria-label", d ? largo(d) : "Sin fecha");
      b.onclick = () => { H.due = d; if (!d) H.hora = ""; $("cal").hidden = true; pinta(); };
      return b;
    });
    const otro = el("button", "c-pil texto");
    otro.type = "button";
    otro.append(el("small", null, lejos ? DIAS[fecha(H.due).getDay()] : "Otro"), el("b", null, lejos ? corta(H.due) : "día…"));
    otro.setAttribute("aria-pressed", !!lejos);
    otro.onclick = () => { $("cal").hidden = !$("cal").hidden; pinta(); };
    $("dias").replaceChildren(...pils, otro);
    if (!$("cal").hidden) pintaMes();
    $("sinhora").setAttribute("aria-pressed", !H.hora);
    $("rueda").classList.toggle("apagada", !H.hora);
  }

  function pintaMes() {
    const HOY = hoy(), [a, m] = H.mes, hueco = (new Date(a, m, 1, 12).getDay() + 6) % 7, n = new Date(a, m + 1, 0).getDate();
    $("mes").textContent = `${MESES_L[m]} ${a}`;
    const celdas = ["L", "M", "X", "J", "V", "S", "D"].map(x => el("i", null, x));
    for (let k = 0; k < hueco; k++) celdas.push(el("span"));
    for (let d = 1; d <= n; d++) {
      const s = new Date(a, m, d, 12).toLocaleDateString("sv"), b = el("button", s < HOY ? "pasado" : s === HOY ? "hoy" : "", String(d));
      b.type = "button";
      b.setAttribute("aria-pressed", s === H.due);
      b.setAttribute("aria-label", largo(s));
      b.onclick = () => { H.due = s; pinta(); };
      celdas.push(b);
    }
    $("rej").replaceChildren(...celdas);
  }

  // una rueda: scroll con imán; la que queda en la lente es la elegida, y las demás se curvan como un tambor
  function rueda(col, valores) {
    col.replaceChildren(...valores.map((v, i) => {
      const d = el("div", null, String(v).padStart(2, "0"));
      d.onclick = () => col.scrollTo({top: i * ALTO, behavior: "smooth"});
      return d;
    }));
    let tmr, pintado = false, programatico = false;
    const curva = () => {
      pintado = false;
      const pos = col.scrollTop / ALTO;
      [...col.children].forEach((d, i) => {
        const o = i - pos;
        d.style.transform = Math.abs(o) > 3 ? "" : `rotateX(${-o * 22}deg) scale(${1 - Math.min(Math.abs(o), 3) * .05})`;
        d.classList.toggle("sel", Math.round(pos) === i);
      });
    };
    col.addEventListener("scroll", () => {
      if (!pintado) { pintado = true; requestAnimationFrame(curva); }
      clearTimeout(tmr);
      tmr = setTimeout(() => {
        if (programatico) { programatico = false; return; }
        lee();                           // mover la rueda es elegir hora; sin día, la hora es de hoy
        if (!H.due) H.due = hoy();
        pinta();
      }, 120);
    }, {passive: true});
    return {pon: v => {
      const y = Math.max(0, valores.indexOf(v)) * ALTO;
      // colocarla al abrir no es elegir hora (si no se mueve, no hay evento que lo desmarque)
      if (Math.round(col.scrollTop) !== y) { programatico = true; col.scrollTop = y; }
      requestAnimationFrame(curva);
    }};
  }
  function lee() {
    const h = Math.max(0, Math.min(23, Math.round($("h").scrollTop / ALTO)));
    const m = MINS[Math.max(0, Math.min(11, Math.round($("m").scrollTop / ALTO)))];
    H.hora = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  }

  function abre({titulo = "Cuándo", texto = null, due = "", hora = "", alGuardar, alBorrar = null}) {
    if (!$) monta();
    antes = document.activeElement;
    Object.assign(H, {due, hora, alGuardar, alBorrar});
    $("borrar").hidden = !alBorrar;
    $("borrar").classList.remove("seguro");
    $("borrar").setAttribute("aria-label", "Borrar la tarea");
    const d = due ? fecha(due) : new Date();
    H.mes = [d.getFullYear(), d.getMonth()];
    $("tit").textContent = titulo;
    $("texto").hidden = texto == null;
    $("texto").value = texto || "";
    $("cal").hidden = !(due && (entre(hoy(), due) < 0 || entre(hoy(), due) > 13));
    pinta();
    document.getElementById("c-velo").classList.add("on");
    document.getElementById("c-hoja").classList.add("on");
    requestAnimationFrame(() => {
      const [h, m] = (hora || "09:00").split(":").map(Number);
      RH.pon(h);
      RM.pon(Math.min(55, Math.round(m / 5) * 5));
      $("dias").querySelector("[aria-pressed=true]")?.scrollIntoView({inline: "center", block: "nearest"});
      (texto == null ? $("ok") : $("texto")).focus({preventScroll: true});
    });
  }
  function cierra() {
    document.getElementById("c-velo").classList.remove("on");
    document.getElementById("c-hoja").classList.remove("on");
    antes?.focus?.({preventScroll: true});
  }

  return {abre, cierra, etiqueta};
})();
