// Small progressive enhancements. Every page also works without JavaScript.
(function () {
  // Show the chosen file names inside drop zones, and allow drag & drop.
  document.querySelectorAll(".dropzone").forEach(function (zone) {
    var input = zone.querySelector("input[type=file]");
    var label = zone.querySelector("[data-file-label]");
    if (!input) return;
    input.addEventListener("change", function () {
      if (!label) return;
      var names = Array.prototype.map.call(input.files, function (f) { return f.name; });
      label.textContent = names.length ? names.join(", ") : label.getAttribute("data-default");
      var form = zone.closest("form");
      var submit = form && form.querySelector("[data-enable-on-file]");
      if (submit) submit.disabled = !names.length;
    });
    ["dragenter", "dragover"].forEach(function (ev) {
      zone.addEventListener(ev, function () { zone.classList.add("drag"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      zone.addEventListener(ev, function () { zone.classList.remove("drag"); });
    });
  });

  // Forms that take a while (CV parsing, test generation) show a full-screen message.
  document.querySelectorAll("form[data-loading]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var overlay = document.getElementById("loading");
      document.getElementById("loading-text").textContent = form.getAttribute("data-loading");
      overlay.classList.add("on");
    });
  });

  // Confirm destructive actions.
  document.querySelectorAll("[data-confirm]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      if (!window.confirm(el.getAttribute("data-confirm"))) e.preventDefault();
    });
  });

  // Enable "Next" in the test once an option is picked.
  var testForm = document.getElementById("test-form");
  if (testForm) {
    var next = document.getElementById("next-btn");
    testForm.addEventListener("change", function () {
      next.disabled = false;
      next.textContent = next.getAttribute("data-label");
    });

    // Countdown; when time is up the server grades the test.
    var timer = document.getElementById("timer");
    var left = parseInt(timer.getAttribute("data-seconds"), 10);
    var resultUrl = timer.getAttribute("data-result-url");
    function tick() {
      var m = Math.floor(left / 60), s = left % 60;
      timer.textContent = m + ":" + (s < 10 ? "0" : "") + s + " left";
      if (left <= 60) timer.classList.add("low");
      if (left <= 0) { window.location.href = resultUrl; return; }
      left -= 1;
      setTimeout(tick, 1000);
    }
    tick();

    // Leaving the test tab is recorded and shown to the company.
    // Moving to the next question also hides the page for a moment, so that is ignored.
    var eventUrl = testForm.getAttribute("data-event-url");
    var token = document.querySelector("meta[name=csrf-token]").content;
    var navigating = false;
    testForm.addEventListener("submit", function () { navigating = true; });
    window.addEventListener("beforeunload", function () { navigating = true; });
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden" && !navigating) {
        fetch(eventUrl, { method: "POST", headers: { "X-CSRF-Token": token }, keepalive: true });
      }
    });
  }
})();
