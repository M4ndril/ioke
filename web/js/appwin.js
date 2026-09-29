// Janela do app instalado (Karaoke.exe): o que so existe nela. Numa aba de navegador
// nada disso aparece.
//   - F11 alterna tela cheia/janela (e fica guardado);
//   - appApi(): as funcoes da janela (tela cheia, fechar o karaoke), ou null no navegador.

let ready = null;

/** As funcoes da janela do app (window.pywebview.api) ou null se for um navegador comum. */
export function appApi() {
  if (!ready) {
    ready = new Promise((resolve) => {
      const done = () => {
        const api = window.pywebview && window.pywebview.api ? window.pywebview.api : null;
        if (api) document.documentElement.classList.add("app-window"); // sem barra de rolagem na pagina
        resolve(api);
      };
      if (window.pywebview && window.pywebview.api && window.pywebview.api.info) return done();
      window.addEventListener("pywebviewready", done, { once: true });
      setTimeout(done, 2500); // navegador comum: o evento nunca vem
    });
  }
  return ready;
}

appApi(); // ja marca a pagina como janela do app

document.addEventListener("keydown", async (e) => {
  if (e.key !== "F11") return;
  const api = await appApi();
  if (!api) return; // no navegador, o F11 dele mesmo
  e.preventDefault();
  api.toggle_fullscreen();
});
