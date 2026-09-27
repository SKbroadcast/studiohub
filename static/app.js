/* StudioHub front-end helpers */

// register page: show freelancer-only fields
function toggleReg(role) {
  var el = document.getElementById("freelancer-fields");
  if (el) el.style.display = role === "freelancer" ? "block" : "none";
}

/* ---------------- 3-dot menu ---------------- */
(function () {
  var btn = document.getElementById("menu-btn");
  var pop = document.getElementById("menu-pop");
  if (!btn || !pop) return;
  btn.addEventListener("click", function (e) {
    e.stopPropagation();
    pop.classList.toggle("open");
  });
  document.addEventListener("click", function (e) {
    if (!pop.contains(e.target)) pop.classList.remove("open");
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") pop.classList.remove("open");
  });
})();

/* ---------------- availability calendar ---------------- */
(function () {
  var cal = document.getElementById("calendar");
  if (!cal) return; // not on freelancer dashboard

  var titleEl = document.getElementById("cal-title");
  var today = new Date();
  var y = today.getFullYear(), m = today.getMonth();
  var free = {};      // date -> true (available)
  var booked = {};    // date -> {type,title,studio,location,district,role,date_str,notes}
  var monthNames = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];

  function fmt(d) { // local YYYY-MM-DD
    var mm = String(d.getMonth() + 1).padStart(2, "0");
    var dd = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + mm + "-" + dd;
  }

  // legacy fallback: booked dates rendered into the page
  document.querySelectorAll("[data-booked-date]").forEach(function (el) {
    if (!booked[el.getAttribute("data-booked-date")]) {
      booked[el.getAttribute("data-booked-date")] = { type: "app", title: "Booked", studio: "", location: "", district: "", role: "", date_str: el.getAttribute("data-booked-date") };
    }
  });

  fetch("/api/availability")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      (data.dates || []).forEach(function (d) {
        var dt = new Date(d + "T00:00:00");
        if (dt >= today) free[d] = true;
      });
      Object.keys(data.booked || {}).forEach(function (d) { booked[d] = data.booked[d]; });
      render();
    });

  function render() {
    cal.innerHTML = "";
    titleEl.textContent = monthNames[m] + " " + y;
    ["S", "M", "T", "W", "T", "F", "S"].forEach(function (d) {
      var el = document.createElement("div");
      el.className = "cal-dow"; el.textContent = d;
      cal.appendChild(el);
    });
    var first = new Date(y, m, 1);
    var daysInMonth = new Date(y, m + 1, 0).getDate();
    for (var i = 0; i < first.getDay(); i++) {
      var pad = document.createElement("div");
      pad.className = "cal-cell other";
      cal.appendChild(pad);
    }
    for (var day = 1; day <= daysInMonth; day++) {
      (function (day) {
        var d = new Date(y, m, day);
        var key = fmt(d);
        var cell = document.createElement("div");
        cell.className = "cal-cell";
        cell.textContent = day;
        if (key === fmt(today)) cell.classList.add("today");
        if (booked[key]) {
          cell.classList.add("booked");
          cell.title = booked[key].title;
          cell.addEventListener("click", function () { showDetails(key); });
        } else if (free[key]) {
          cell.classList.add("free");
          if (d >= today) cell.addEventListener("click", function () { toggle(key, cell); });
        } else if (d >= today) {
          cell.addEventListener("click", function () { toggle(key, cell); });
        }
        cal.appendChild(cell);
      })(day);
    }
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return "&#" + c.charCodeAt(0) + ";";
    });
  }

  function showDetails(key) {
    var b = booked[key];
    if (!b) return;
    var html = '<div class="cal-modal" id="cal-modal"><div class="cal-modal-box">' +
      "<h3>" + (b.type === "note" ? "📝 " : "🎬 ") + esc(b.title) + "</h3>" +
      "<p><span class='muted'>Date:</span> " + esc(b.date_str || key) + "</p>" +
      (b.role ? "<p><span class='muted'>Role:</span> " + esc(b.role) + "</p>" : "") +
      (b.studio ? "<p><span class='muted'>Studio:</span> " + esc(b.studio) + "</p>" : "") +
      (b.location ? "<p><span class='muted'>Location:</span> " + esc(b.location) + "</p>" : "") +
      (b.district ? "<p><span class='muted'>District:</span> " + esc(b.district) + "</p>" : "") +
      (b.notes ? "<p><span class='muted'>Notes:</span> " + esc(b.notes) + "</p>" : "") +
      "<p><span class='muted'>Type:</span> " + (b.type === "note" ? "Noted by me (outside booking)" : "Booked through StudioHub") + "</p>" +
      '<button class="btn btn-primary cal-modal-close" onclick="document.getElementById(\'cal-modal\').remove()">Close</button>' +
      "</div></div>";
    var old = document.getElementById("cal-modal");
    if (old) old.remove();
    document.body.insertAdjacentHTML("beforeend", html);
    document.getElementById("cal-modal").addEventListener("click", function (e) {
      if (e.target === this) this.remove();
    });
  }

  function toggle(key, cell) {
    fetch("/api/availability", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: key })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) { alert(data.error || "Could not update"); return; }
        free[key] = data.available;
        if (!data.available) delete free[key];
        render();
      });
  }

  document.getElementById("cal-prev").addEventListener("click", function () {
    m--; if (m < 0) { m = 11; y--; } render();
  });
  document.getElementById("cal-next").addEventListener("click", function () {
    m++; if (m > 11) { m = 0; y++; } render();
  });
})();
