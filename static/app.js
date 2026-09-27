/* StudioHub front-end helpers */

// register page: show freelancer-only fields
function toggleReg(role) {
  var el = document.getElementById("freelancer-fields");
  if (el) el.style.display = role === "freelancer" ? "block" : "none";
}

/* ---------------- availability calendar ---------------- */
(function () {
  var cal = document.getElementById("calendar");
  if (!cal) return; // not on freelancer dashboard

  var titleEl = document.getElementById("cal-title");
  var today = new Date();
  var y = today.getFullYear(), m = today.getMonth();
  var free = {};      // date -> true (available)
  var booked = {};    // date -> true (confirmed booking)
  var monthNames = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];

  function fmt(d) { // local YYYY-MM-DD
    var mm = String(d.getMonth() + 1).padStart(2, "0");
    var dd = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + mm + "-" + dd;
  }

  // collect already-booked dates from the page (server-rendered booking list)
  document.querySelectorAll("[data-booked-date]").forEach(function (el) {
    booked[el.getAttribute("data-booked-date")] = true;
  });

  fetch("/api/availability")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      (data.dates || []).forEach(function (d) {
        var dt = new Date(d + "T00:00:00");
        if (dt >= today) free[d] = true;
      });
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
        if (booked[key]) cell.classList.add("booked");
        else if (free[key]) cell.classList.add("free");
        if (d >= today && !booked[key]) {
          cell.addEventListener("click", function () { toggle(key, cell); });
        }
        cal.appendChild(cell);
      })(day);
    }
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
