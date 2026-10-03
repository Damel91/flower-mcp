"use strict";

const documents = new Map(
  Array.from(document.querySelectorAll("article[data-document]"), article => [article.dataset.document, article])
);
const navigation = document.getElementById("navigation");
const errorMessage = document.getElementById("route-error");
const languageSwitch = document.getElementById("language-switch");
const otherEdition = languageSwitch.getAttribute("href");
const mobile = window.matchMedia("(max-width: 780px)");
navigation.open = !mobile.matches;
mobile.addEventListener("change", event => { navigation.open = !event.matches; });

function displayRoute() {
  const parameters = new URLSearchParams(location.hash.slice(1));
  const requested = parameters.get("page") || "README.md";
  const page = documents.has(requested) ? requested : "README.md";
  const article = documents.get(page);
  errorMessage.hidden = requested === page;
  errorMessage.textContent = requested === page ? "" : errorMessage.dataset.missingPage;
  languageSwitch.setAttribute("href", otherEdition + "#" + new URLSearchParams({page}));
  for (const [path, candidate] of documents) candidate.hidden = path !== page;
  for (const link of navigation.querySelectorAll("a[data-page]")) {
    if (link.dataset.page === page) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  const section = parameters.get("section");
  const target = section && document.getElementById(article.dataset.prefix + "--" + section);
  if (section && !target) {
    errorMessage.hidden = false;
    errorMessage.textContent = errorMessage.dataset.missingSection;
  }
  const focus = target || article.querySelector("h1");
  document.title = article.dataset.title + " | Flower MCP";
  focus.setAttribute("tabindex", "-1");
  focus.focus({preventScroll: true});
  if (location.hash) focus.scrollIntoView({block: "start"});
  if (mobile.matches) navigation.open = false;
}

document.addEventListener("click", event => {
  if (event.target.closest(".skip-link")) {
    event.preventDefault();
    const content = document.getElementById("content");
    content.focus({preventScroll: true});
    content.scrollIntoView({block: "start"});
    return;
  }
  const link = event.target.closest("a[data-page]");
  if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  const parameters = new URLSearchParams({page: link.dataset.page});
  if (link.dataset.section) parameters.set("section", link.dataset.section);
  const next = "#" + parameters.toString();
  if (location.hash === next) displayRoute();
  else location.hash = next;
});

window.addEventListener("hashchange", displayRoute);
displayRoute();
