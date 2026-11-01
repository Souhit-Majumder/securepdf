import React, { useState } from "react";
import { Shield, Lock, User as UserIcon, AlertCircle, Loader2, ArrowRight } from "lucide-react";
import { UserDTO } from "../types/auth";
import { getSafeRedirect } from "../utils/safeRedirect";

interface LoginPageProps {
  currentUser: UserDTO | null;
  onLoginSuccess: (user: UserDTO) => void;
  onNavigate: (path: string) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({
  currentUser,
  onLoginSuccess,
  onNavigate,
}) => {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // If already authenticated
  if (currentUser) {
    return (
      <div className="relative w-screen h-screen flex items-center justify-center spatial-bg p-4 overflow-hidden">
        <div className="w-full max-w-md rounded-3xl glass-top-island p-8 border border-white/95 shadow-2xl text-center space-y-5 animate-in fade-in zoom-in-95 duration-200">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-sky-500/15 border border-sky-400/40 flex items-center justify-center text-sky-600 shadow-sm">
            <Shield className="w-7 h-7" />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-slate-900 tracking-tight">Already Signed In</h2>
            <p className="text-xs text-slate-500 mt-1">
              You are currently logged in as <span className="font-semibold text-slate-800">{currentUser.username}</span> ({currentUser.email}).
            </p>
          </div>
          <button
            onClick={() => onNavigate("/")}
            className="w-full py-2.5 px-4 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-medium text-xs tracking-wide transition shadow-md flex items-center justify-center gap-2 cursor-pointer"
          >
            <span>Go to Inspection Workspace</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (!identifier.trim()) {
      setErrorMessage("Please enter your email or username.");
      return;
    }
    if (!password) {
      setErrorMessage("Please enter your password.");
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          identifier: identifier.trim(),
          password,
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Authentication failed. Please check your credentials.");
      }

      onLoginSuccess(data.user);

      // Return to safe redirect target or default to workspace
      const searchParams = new URLSearchParams(window.location.search);
      const redirectTarget = getSafeRedirect(searchParams.get("redirect"));
      onNavigate(redirectTarget);
    } catch (err: any) {
      setErrorMessage(err.message || "An unexpected network error occurred.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative w-screen h-screen flex items-center justify-center spatial-bg p-4 overflow-hidden">
      {/* Daylight Liquid-Glass Center Card */}
      <div className="w-full max-w-md rounded-3xl glass-top-island p-8 border border-white/95 shadow-2xl space-y-6 animate-in fade-in zoom-in-95 duration-200">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div className="w-12 h-12 mx-auto rounded-2xl bg-sky-500/15 border border-sky-400/35 flex items-center justify-center text-sky-600 shadow-xs">
            <Lock className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">Sign In to SecurePDF</h1>
            <p className="text-xs text-slate-500 mt-1">
              Access your protected documents and distribution batches
            </p>
          </div>
        </div>

        {/* Error Alert */}
        {errorMessage && (
          <div className="flex items-start gap-2.5 p-3 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-xs animate-in fade-in duration-150">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-500" />
            <div className="flex-1 font-medium">{errorMessage}</div>
          </div>
        )}

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider block">
              Email or Username
            </label>
            <div className="relative">
              <UserIcon className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                placeholder="you@institution.edu or username"
                disabled={isLoading}
                autoFocus
                className="w-full pl-10 pr-3.5 py-2.5 rounded-xl bg-white/70 border border-slate-200 focus:border-sky-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-500/20 text-xs text-slate-900 placeholder:text-slate-400 transition"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider block">
              Password
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your account password"
                disabled={isLoading}
                className="w-full pl-10 pr-3.5 py-2.5 rounded-xl bg-white/70 border border-slate-200 focus:border-sky-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-500/20 text-xs text-slate-900 placeholder:text-slate-400 transition"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2.5 px-4 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-medium text-xs tracking-wide transition shadow-md flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed mt-2"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Authenticating...</span>
              </>
            ) : (
              <>
                <span>Sign In</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </>
            )}
          </button>
        </form>

        {/* Footer Navigation */}
        <div className="pt-2 border-t border-slate-200/60 flex flex-col items-center gap-2.5 text-xs">
          <button
            type="button"
            onClick={() => {
              const search = window.location.search;
              onNavigate(`/register${search}`);
            }}
            className="text-slate-600 hover:text-sky-600 font-medium transition cursor-pointer"
          >
            Don't have an account? <span className="text-sky-600 underline font-semibold">Create account</span>
          </button>
        </div>
      </div>
    </div>
  );
};
