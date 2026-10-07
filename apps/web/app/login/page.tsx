"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [token, setToken] = useState("");

  const supabase = createClient();

  const handleSignUp = async () => {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
    });
    if (error) setMessage(`Error: ${error.message}`);
    else setMessage("Sign up successful! Check your email or try logging in.");
  };

  const handleLogIn = async () => {
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (error) {
      setMessage(`Error: ${error.message}`);
    } else {
      setMessage("Login successful!");
      const sessionToken = data.session?.access_token || "";
      setToken(sessionToken);
    }
  };

  const testProtectedBackend = async () => {
    if (!token) {
      setMessage("Please log in first to get JWT token.");
      return;
    }
    try {
      const res = await fetch("http://localhost:8000/auth/me", {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      const data = await res.json();
      setMessage(`Backend Response: ${JSON.stringify(data)}`);
    } catch (err: any) {
      setMessage(`Fetch Error: ${err.message}`);
    }
  };

  return (
    <div
      style={{
        maxWidth: "400px",
        margin: "50px auto",
        fontFamily: "sans-serif",
        padding: "20px",
        border: "1px solid #ccc",
        borderRadius: "8px",
      }}
    >
      <h2>VidyaPulse AI Auth</h2>
      <div style={{ marginBottom: "10px" }}>
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{ width: "100%", padding: "8px", marginBottom: "8px" }}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ width: "100%", padding: "8px", marginBottom: "8px" }}
        />
      </div>
      <div style={{ display: "flex", gap: "10px", marginBottom: "15px" }}>
        <button onClick={handleSignUp} style={{ padding: "8px 12px" }}>
          Sign Up
        </button>
        <button onClick={handleLogIn} style={{ padding: "8px 12px" }}>
          Log In
        </button>
      </div>
      <button
        onClick={testProtectedBackend}
        style={{
          width: "100%",
          padding: "8px",
          backgroundColor: "#0070f3",
          color: "white",
          border: "none",
          borderRadius: "4px",
        }}
      >
        Test FastAPI `/auth/me`
      </button>
      {message && (
        <p
          style={{
            marginTop: "15px",
            wordBreak: "break-all",
            fontSize: "14px",
          }}
        >
          {message}
        </p>
      )}
    </div>
  );
}
