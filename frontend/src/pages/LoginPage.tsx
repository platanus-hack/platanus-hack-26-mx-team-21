import { useState, type FormEvent } from "react";
import { useAuth } from "../lib/auth";

export function LoginPage() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("author.a@citycrawl.test");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await signIn(email.trim(), password);
    if (error) setError(traducirError(error));
    setBusy(false);
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background:
          "radial-gradient(1200px 600px at 70% -10%, #e7edf9, #eef1f5 60%)",
        padding: 20,
      }}
    >
      <div
        style={{
          width: 380,
          background: "rgba(255,255,255,.95)",
          backdropFilter: "blur(16px)",
          border: "1px solid rgba(230,233,238,.9)",
          borderRadius: 18,
          boxShadow: "0 26px 64px -32px rgba(20,30,50,.5)",
          overflow: "hidden",
          animation: "ppin .25s ease",
        }}
      >
        <div style={{ padding: "22px 22px 6px", display: "flex", alignItems: "center", gap: 11 }}>
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: 10,
              background: "#1b2430",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flex: "none",
            }}
          >
            <div
              style={{
                width: 15,
                height: 15,
                border: "3px solid #fff",
                borderRadius: "50%",
                position: "relative",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  width: 4,
                  height: 4,
                  background: "#fff",
                  borderRadius: "50%",
                  top: "50%",
                  left: "50%",
                  transform: "translate(-50%,-50%)",
                }}
              />
            </div>
          </div>
          <div style={{ lineHeight: 1.12 }}>
            <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-.3px" }}>CityCrawl</div>
            <div style={{ fontSize: 11, color: "#9aa3b1", fontWeight: 500 }}>
              CDMX · Mapa de prioridades
            </div>
          </div>
        </div>

        <form onSubmit={onSubmit} style={{ padding: "12px 22px 22px" }}>
          <div style={{ fontSize: 13, color: "#5b6675", margin: "8px 0 16px", lineHeight: 1.5 }}>
            Inicia sesión para ver el mapa de observaciones y planear reparaciones.
          </div>

          <label style={labelStyle}>Correo</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            style={inputStyle}
            placeholder="tu@correo.com"
          />

          <label style={{ ...labelStyle, marginTop: 12 }}>Contraseña</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            style={inputStyle}
            placeholder="••••••••"
          />

          {error && (
            <div
              style={{
                marginTop: 12,
                fontSize: 12,
                color: "#e5484d",
                background: "#fdeceb",
                border: "1px solid #f8d8d6",
                borderRadius: 9,
                padding: "8px 11px",
              }}
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            style={{
              marginTop: 18,
              width: "100%",
              height: 42,
              border: "none",
              borderRadius: 11,
              background: "var(--acc,#2f64e6)",
              color: "#fff",
              fontFamily: "Public Sans, sans-serif",
              fontSize: 13.5,
              fontWeight: 700,
              cursor: busy ? "default" : "pointer",
              opacity: busy ? 0.7 : 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 9,
            }}
          >
            {busy && (
              <span
                style={{
                  width: 15,
                  height: 15,
                  border: "2px solid rgba(255,255,255,.5)",
                  borderTopColor: "#fff",
                  borderRadius: "50%",
                  animation: "ppspin .7s linear infinite",
                  display: "inline-block",
                }}
              />
            )}
            {busy ? "Entrando…" : "Iniciar sesión"}
          </button>

          {import.meta.env.DEV && (
            <div
              style={{
                marginTop: 16,
                fontSize: 10.5,
                color: "#9aa3b1",
                fontFamily: "IBM Plex Mono, monospace",
                lineHeight: 1.6,
                borderTop: "1px solid #f3f5f8",
                paddingTop: 12,
              }}
            >
              Demo · author.a@citycrawl.test
              <br />
              contraseña: citycrawl-dev-2026!
            </div>
          )}
        </form>
      </div>
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 10,
  letterSpacing: ".5px",
  fontWeight: 700,
  color: "#8a94a3",
  textTransform: "uppercase",
  marginBottom: 6,
};
const inputStyle: React.CSSProperties = {
  width: "100%",
  height: 40,
  border: "1px solid #e3e7ee",
  borderRadius: 11,
  padding: "0 13px",
  fontFamily: "Public Sans, sans-serif",
  fontSize: 14,
  outline: "none",
  background: "#fff",
};

function traducirError(msg: string): string {
  if (/invalid login credentials/i.test(msg)) return "Correo o contraseña incorrectos.";
  if (/email not confirmed/i.test(msg)) return "El correo no está confirmado.";
  return msg;
}
