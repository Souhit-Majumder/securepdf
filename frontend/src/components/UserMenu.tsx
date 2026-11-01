import React, { useState, useRef, useEffect } from "react";
import { User as UserIcon, LogOut, CheckCircle2, Loader2 } from "lucide-react";
import { UserDTO } from "../types/auth";

interface UserMenuProps {
  user: UserDTO;
  onLogout: () => Promise<void>;
}

export const UserMenu: React.FC<UserMenuProps> = ({
  user,
  onLogout,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener("mousedown", handleOutsideClick);
    }
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
    };
  }, [isOpen]);

  const handleSignOut = async () => {
    setIsLoggingOut(true);
    try {
      await onLogout();
      setIsOpen(false);
    } finally {
      setIsLoggingOut(false);
    }
  };

  return (
    <div className="relative" ref={menuRef}>
      {/* Header Button */}
      <button
        onClick={() => setIsOpen((prev) => !prev)}
        title={`${user.username} (${user.email})`}
        className="w-7 h-7 rounded-full flex items-center justify-center transition shadow-xs cursor-pointer bg-sky-500/15 border border-sky-400/40 text-sky-700 hover:bg-sky-500/25"
      >
        <UserIcon className="w-3.5 h-3.5" />
      </button>

      {/* Authenticated Dropdown Popover */}
      {user && isOpen && (
        <div className="absolute right-0 top-9 z-40 w-56 rounded-2xl glass-top-island p-3 shadow-2xl border border-white/90 animate-in fade-in zoom-in-95 duration-150 space-y-2.5 text-slate-800">
          {/* User info */}
          <div className="border-b border-slate-200/60 pb-2">
            <div className="flex items-center gap-1.5 text-emerald-600 text-[10px] font-semibold tracking-wide">
              <CheckCircle2 className="w-3 h-3" />
              <span>AUTHENTICATED</span>
            </div>
            <div className="font-semibold text-xs text-slate-900 truncate mt-0.5">
              {user.username}
            </div>
            <div className="text-[11px] text-slate-500 truncate">
              {user.email}
            </div>
          </div>

          {/* Sign Out Button */}
          <button
            onClick={handleSignOut}
            disabled={isLoggingOut}
            className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-700 border border-rose-300/40 text-xs font-medium transition cursor-pointer disabled:opacity-50"
          >
            <span>{isLoggingOut ? "Signing out..." : "Sign Out"}</span>
            {isLoggingOut ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <LogOut className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      )}
    </div>
  );
};
