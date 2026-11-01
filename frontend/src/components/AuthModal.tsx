import React, { useState, useEffect } from "react";
import { X, Lock, Mail, User as UserIcon, AlertCircle, Loader2, ArrowRight } from "lucide-react";
import { UserDTO } from "../types/auth";

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAuthSuccess: (user: UserDTO) => void;
  initialMode?: "login" | "register";
}

export const AuthModal: React.FC<AuthModalProps> = ({
  isOpen,
  onClose,
  onAuthSuccess,
  initialMode = "login",
}) => {
  const [mode, setMode] = useState<"login" | "register">(initialMode);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Sync mode if initialMode changes
  useEffect(() => {
    if (isOpen) {
      setMode(initialMode);
      setErrorMessage(null);
    }
  }, [isOpen, initialMode]);

  // Handle ESC key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !isLoading) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isLoading, onClose]);

  if (!isOpen) return null;

  const resetForm = () => {
    setEmail("");
    setUsername("");
    setPassword("");
    setIdentifier("");
    setErrorMessage(null);
  };

  const handleSwitchMode = (newMode: "login" | "register") => {
    setMode(newMode);
    setErrorMessage(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    // Client-side validation
    if (mode === "login") {
      if (!identifier.trim()) {
        setErrorMessage("Please enter your email or username.");
        return;
      }
      if (!password) {
        setErrorMessage("Please enter your password.");
        return;
      }
    } else {
      if (!email.trim() || !email.includes("@")) {
        setErrorMessage("Please enter a valid email address.");
        return;
      }
      if (!username.trim() || username.trim().length < 3) {
        setErrorMessage("Username must be at least 3 characters.");
        return;
      }
      if (!password || password.length < 8) {
        setErrorMessage("Password must be at least 8 characters.");
        return;
      }
    }

    setIsLoading(true);

    try {
      const endpoint = mode === "login" ? "/api/auth/login" : "/api/auth/register";
      const payload =
        mode === "login"
          ? { identifier: identifier.trim(), password }
          : { email: email.trim(), username: username.trim(), password };

      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify(payload),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        let errorDetail = "Authentication failed.";
        if (typeof data.detail === "string") {
          errorDetail = data.detail;
        } else if (Array.isArray(data.detail) && data.detail[0]?.msg) {
          errorDetail = data.detail[0].msg;
        }
        throw new Error(errorDetail);
      }

      const user: UserDTO = data;
      resetForm();
      onAuthSuccess(user);
      onClose();
    } catch (err: any) {
      setErrorMessage(err.message || "An unexpected error occurred. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-md animate-in fade-in duration-200"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isLoading) {
          onClose();
        }
      }}
    >
      <div
        className="w-full max-w-sm rounded-2xl glass-dock-dark p-6 space-y-4 shadow-2xl border border-white/20 text-slate-100 animate-in zoom-in-95 duration-200"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-modal-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 pb-3">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-sky-500/20 text-sky-300 border border-sky-400/30">
              <Lock className="w-4 h-4" />
            </div>
            <div>
              <h2 id="auth-modal-title" className="text-sm font-semibold tracking-tight text-white">
                {mode === "login" ? "Sign In to SecurePDF" : "Create Investigator Account"}
              </h2>
              <p className="text-[10px] text-slate-300">
                {mode === "login"
                  ? "Access your protected forensic sessions"
                  : "Register for authenticated workspace access"}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isLoading}
            className="p-1 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition disabled:opacity-40"
            title="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Mode Selector Tabs */}
        <div className="flex p-0.5 rounded-xl bg-black/20 border border-white/10">
          <button
            type="button"
            onClick={() => handleSwitchMode("login")}
            className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition ${
              mode === "login"
                ? "bg-white/15 text-white shadow-xs border border-white/20"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => handleSwitchMode("register")}
            className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition ${
              mode === "register"
                ? "bg-white/15 text-white shadow-xs border border-white/20"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Register
          </button>
        </div>

        {/* Error Banner */}
        {errorMessage && (
          <div className="flex items-start gap-2 p-2.5 rounded-xl bg-rose-500/20 border border-rose-400/30 text-rose-200 text-xs animate-in fade-in duration-150">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
            <div className="leading-tight text-[11px]">{errorMessage}</div>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-3.5 pt-1">
          {mode === "login" ? (
            <>
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-slate-300">
                  Email or Username
                </label>
                <div className="relative">
                  <UserIcon className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                  <input
                    type="text"
                    required
                    autoFocus
                    placeholder="investigator@example.com or username"
                    value={identifier}
                    onChange={(e) => setIdentifier(e.target.value)}
                    disabled={isLoading}
                    className="w-full pl-9 pr-3 py-2 rounded-xl bg-white/10 border border-white/20 text-xs text-white placeholder-slate-400 focus:outline-hidden focus:border-sky-400 transition"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-medium text-slate-300">
                  Password
                </label>
                <div className="relative">
                  <Lock className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                  <input
                    type="password"
                    required
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={isLoading}
                    className="w-full pl-9 pr-3 py-2 rounded-xl bg-white/10 border border-white/20 text-xs text-white placeholder-slate-400 focus:outline-hidden focus:border-sky-400 transition"
                  />
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-slate-300">
                  Email Address
                </label>
                <div className="relative">
                  <Mail className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                  <input
                    type="email"
                    required
                    autoFocus
                    placeholder="investigator@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={isLoading}
                    className="w-full pl-9 pr-3 py-2 rounded-xl bg-white/10 border border-white/20 text-xs text-white placeholder-slate-400 focus:outline-hidden focus:border-sky-400 transition"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-medium text-slate-300">
                  Username
                </label>
                <div className="relative">
                  <UserIcon className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                  <input
                    type="text"
                    required
                    placeholder="investigator_id"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    disabled={isLoading}
                    className="w-full pl-9 pr-3 py-2 rounded-xl bg-white/10 border border-white/20 text-xs text-white placeholder-slate-400 focus:outline-hidden focus:border-sky-400 transition"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-medium text-slate-300">
                  Password (min 8 chars)
                </label>
                <div className="relative">
                  <Lock className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                  <input
                    type="password"
                    required
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={isLoading}
                    className="w-full pl-9 pr-3 py-2 rounded-xl bg-white/10 border border-white/20 text-xs text-white placeholder-slate-400 focus:outline-hidden focus:border-sky-400 transition"
                  />
                </div>
              </div>
            </>
          )}

          {/* Submit Button */}
          <button
            type="submit"
            disabled={isLoading}
            className="w-full mt-2 py-2 px-4 rounded-xl bg-sky-500/30 hover:bg-sky-500/40 border border-sky-400/40 text-xs font-semibold text-white shadow-sm shadow-sky-500/20 transition disabled:opacity-40 flex items-center justify-center gap-2 cursor-pointer"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>{mode === "login" ? "Signing In..." : "Creating Account..."}</span>
              </>
            ) : (
              <>
                <span>{mode === "login" ? "Sign In" : "Register"}</span>
                <ArrowRight className="w-3.5 h-3.5 text-sky-300" />
              </>
            )}
          </button>
        </form>

        {/* Footer Toggle */}
        <div className="pt-2 text-center text-[11px] text-slate-400 border-t border-white/10">
          {mode === "login" ? (
            <span>
              Don't have an account?{" "}
              <button
                type="button"
                onClick={() => handleSwitchMode("register")}
                disabled={isLoading}
                className="text-sky-300 hover:text-sky-200 font-medium underline underline-offset-2 transition"
              >
                Create one
              </button>
            </span>
          ) : (
            <span>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => handleSwitchMode("login")}
                disabled={isLoading}
                className="text-sky-300 hover:text-sky-200 font-medium underline underline-offset-2 transition"
              >
                Sign in
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
