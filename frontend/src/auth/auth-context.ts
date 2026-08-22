import { createContext, useContext } from "react";


export type AuthContextValue = {
  githubLogin: string;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside AuthGate");
  }
  return context;
}
