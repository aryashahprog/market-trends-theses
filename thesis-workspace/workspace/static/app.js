const form = document.querySelector("[data-research]");
if (form) {
  const sync = () => {
    const kind = form.querySelector('input[name="kind"]:checked')?.value;
    const isNew = form.elements.namedItem("thesis").value === "new";
    for (const section of form.querySelectorAll("[data-kind], [data-new]")) {
      const active = section.hasAttribute("data-new") ? isNew : section.dataset.kind === kind;
      section.hidden = !active;
      for (const element of section.querySelectorAll("input, select, textarea")) {
        element.disabled = !active;
      }
    }
  };
  form.addEventListener("change", sync);
  window.addEventListener("pageshow", () => setTimeout(sync, 0));
  sync();
}
for (const capture of document.querySelectorAll("[data-research], [data-assign]")) {
  const thesis = capture.elements.namedItem("thesis");
  const newScope = capture.elements.namedItem("new_visibility");
  const label = capture.querySelector("[data-evidence-scope]");
  const scope = label.querySelector("select");
  const save = capture.querySelector("[data-save-research]");
  const syncScope = () => {
    const targetScope = thesis.value === "new" ? newScope.value : thesis.selectedOptions[0]?.dataset.scope;
    label.hidden = targetScope !== "team";
    if (label.hidden) scope.value = "draft";
    if (save) save.textContent = scope.value === "team" ? "Share research" : "Save private research";
  };
  capture.addEventListener("change", syncScope);
  window.addEventListener("pageshow", () => setTimeout(syncScope, 0));
  syncScope();
}
const filters = document.querySelector("[data-filters]");
filters?.addEventListener("change", ({ target }) => {
  if (target.matches("select")) filters.requestSubmit();
});
for (const button of document.querySelectorAll("[data-question]")) {
  button.addEventListener("click", () => {
    const input = document.querySelector("#question");
    input.value = button.dataset.question;
    input.focus();
  });
}
