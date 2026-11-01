import React, { useState } from "react";
import { Shield, Lock, Mail, User as UserIcon, AlertCircle, Loader2, ArrowRight, CheckCircle2 } from "lucide-react";
import { UserDTO } from "../types/auth";
import { getSafeRedirect } from "../utils/safeRedirect";

interface RegisterPageProps {
  currentUser: UserDTO | null;
  onRegisterSuccess: (user: UserDTO) => void;
  onNavigate: (path: string) => void;
}

export const RegisterPage: React.FC<RegisterPageProps> = ({
  currentUser,
  onRegisterSuccess,
  onNavigate,
}) => {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // If already authenticated
  if (currentUser) {
    return (
      <div className="relative w-screen h-screen flex items-center justify-center spatial-bg p-4 overflow-hidden">
        <div className="w-full max-w-md rounded-3xl glass-top-island p-8 border border-white/95 shadow-2xl text-center space-y-5 animate-in fade-in zoom-in-95 duration-200">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-emerald-500/15 border border-emerald-400/40 flex items-center justify-center text-emerald-600 shadow-sm">
            <CheckCircle2 className="w-7 h-7" />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-slate-900 tracking-tight">Active Account Detected</h2>
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

    // Client-side validations
    if (!email.trim() || !email.includes("@")) {
      setErrorMessage("Please enter a valid email address.");
      return;
    }
    if (!username.trim() || username.trim().length < 3) {
      setErrorMessage("Username must be at least 3 characters long.");
      return;
    }
    if (!password || password.length < 8) {
      setErrorMessage("Password must be at least 8 characters long.");
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          email: email.trim(),
          username: username.trim(),
          password,
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Registration failed. Please try a different email or username.");
      }

      onRegisterSuccess(data.user);

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
            <Shield className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">Create an Account</h1>
            <p className="text-xs text-slate-500 mt-1">
              Start distributing and watermarking documents securely
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

        {/* Register Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider block">
              Email Address
            </label>
            <div className="relative">
              <Mail className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@institution.edu"
                disabled={isLoading}
                autoFocus
                className="w-full pl-10 pr-3.5 py-2.5 rounded-xl bg-white/70 border border-slate-200 focus:border-sky-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-500/20 text-xs text-slate-900 placeholder:text-slate-400 transition"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider block">
              Username
            </label>
            <div className="relative">
              <UserIcon className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="e.g. jsmith or prof_carol"
                disabled={isLoading}
                className="w-full pl-10 pr-3.5 py-2.5 rounded-xl bg-white/70 border border-slate-200 focus:border-sky-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-500/20 text-xs text-slate-900 placeholder:text-slate-400 transition"
              />
            </div>
            <p className="text-[10px] text-slate-400">At least 3 characters</p>
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
                placeholder="At least 8 characters"
                disabled={isLoading}
                className="w-full pl-10 pr-3.5 py-2.5 rounded-xl bg-white/70 border border-slate-200 focus:border-sky-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-500/20 text-xs text-slate-900 placeholder:text-slate-400 transition"
              />
            </div>
            <p className="text-[10px] text-slate-400">Must be at least 8 characters long</p>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2.5 px-4 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-medium text-xs tracking-wide transition shadow-md flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed mt-2"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Creating Account...</span>
              </>
            ) : (
              <>
                <span>Create Account</span>
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
              onNavigate(`/login${search}`);
            }}
            className="text-slate-600 hover:text-sky-600 font-medium transition cursor-pointer"
          >
            Already have an account? <span className="text-sky-600 underline font-semibold">Sign in</span>
          </button>
        </div>
      </div>
    </div>
  );
};
