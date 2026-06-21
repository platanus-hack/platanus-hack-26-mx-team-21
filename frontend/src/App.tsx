import { useAuth } from "./lib/auth";
import { LoginPage } from "./pages/LoginPage";
import { MapPage } from "./pages/MapPage";

export function App() {
  const { session, loading } = useAuth();

  if (loading) {
    return (
      <div
        style={{
          position: "fixed",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#eef1f5",
          color: "#8a94a3",
          fontSize: 13,
          gap: 11,
        }}
      >
        <span
          style={{
            width: 22,
            height: 22,
            border: "3px solid #e3e7ee",
            borderTopColor: "#2f64e6",
            borderRadius: "50%",
            animation: "ppspin .7s linear infinite",
            display: "inline-block",
          }}
        />
        Cargando…
      </div>
    );
  }

  return session ? <MapPage /> : <LoginPage />;
}
