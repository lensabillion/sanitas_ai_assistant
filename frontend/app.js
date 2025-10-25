const API_URL = (
  localStorage.getItem("apiUrl") || "https://sanitas-ai-assistant.onrender.com"
).replace(/\/$/, "");

document.addEventListener("DOMContentLoaded", () => {
  const lbl = document.getElementById("apiUrlLabel");
  if (lbl) lbl.textContent = API_URL;
});

const chat = document.getElementById("chat");
const chips = document.getElementById("chips");
const results = document.getElementById("results");
const input = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const status = document.getElementById("status");

function addMessage(text, who) {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function showSpecialties(specs) {
  if (!specs || !specs.length) {
    chips.style.display = "none";
    chips.innerHTML = "";
    return;
  }
  chips.innerHTML = "";
  specs.forEach((s) => {
    const c = document.createElement("span");
    c.className = "chip";
    c.textContent = s;
    chips.appendChild(c);
  });
  chips.style.display = "flex";
}

function formatContacts(raw) {
  if (!raw) return "N/A";
  return raw
    .split(/[;,]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .join(" • ");
}

function showResults(items) {
  if (!items || !items.length) {
    results.style.display = "none";
    results.innerHTML = "";
    return;
  }
  results.innerHTML = "";
  items.forEach((d) => {
    const card = document.createElement("div");
    card.className = "doc";
    const name = (d.name || "").trim() || "Doctor";
    const spec = d.specialization || "";
    const contact = formatContacts(d.contact);

    card.innerHTML = `
      <h4>${name}</h4>
      <div class="muted">${spec}</div>
      <div class="muted" style="margin-top:8px">Contact: ${contact}</div>
    `;
    results.appendChild(card);
  });
  results.style.display = "grid";
}

async function sendMessage() {
  const text = input.value.trim();
  if (!text) return;
  input.value = "";

  addMessage(text, "user");
  const botNode = addMessage("Thinking…", "bot");
  status.textContent = "WORKING";
  sendBtn.disabled = true;

  // keep data in outer scope so we can safely reference it
  let data = null;

  try {
    // --- Call /triage ---
    const r = await fetch(`${API_URL}/triage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symptoms: text }),
    });

    if (!r.ok) {
      const eText = await r.text();
      throw new Error(`HTTP ${r.status}: ${eText}`);
    }

    data = await r.json();

    // Update disclaimer if present
    const disclaim = document.getElementById("disclaimer");
    if (disclaim && data.disclaimer) disclaim.textContent = data.disclaimer;

    // If you want chips back later, uncomment:
    // showSpecialties(
    //   data.interpreted_specialties_es_in || data.interpreted_specialties || []
    // );

    // Results: only Name, Specialty, Contact
    const doctors = data.matched_doctors || [];
    showResults(doctors);

    // Use the GPT-provided empathetic line (with a safe fallback)
    const opening = (data.opening_message || "").trim();
    botNode.textContent =
      opening ||
      (doctors.length
        ? "Here are a few doctors you can visit."
        : "I couldn’t find matching doctors. Try adding more detail (duration, severity, body area).");

    // --- Log the symptom (fire-and-forget) ---
    // "Symptom" if either interpreted or resolved lists are non-empty
    const isSymptom =
      (data.interpreted_specialties_es_in &&
        data.interpreted_specialties_es_in.length > 0) ||
      (data.resolved_specialties_in_db &&
        data.resolved_specialties_in_db.length > 0);

    if (isSymptom) {
      fetch(`${API_URL}/symptoms/log`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          interpreted_specialties_es: data.interpreted_specialties_es_in || [],
          resolved_specialties: data.resolved_specialties_in_db || [],
          is_symptom_query: true,
          force_english: true, // keep analytics English-only
        }),
      }).catch(() => {});
    }
  } catch (err) {
    botNode.textContent = "Error: " + (err?.message || String(err));
  } finally {
    status.textContent = "READY";
    sendBtn.disabled = false;
    chat.scrollTop = chat.scrollHeight;
  }
}

// Convenience: pre-fill input when page loads
window.addEventListener("load", () => {
  input.value = "";
  addMessage(
    "👋 Hello! I'm your virtual assistant here to help you find doctors based on your symptoms. " +
      "Describe what you're feeling, and I'll suggest specialists and nearby doctors for you.",
    "bot"
  );
  status.textContent = "READY";
});
