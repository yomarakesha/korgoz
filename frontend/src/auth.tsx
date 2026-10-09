// Who is logged in, available to every page. Admin-only controls check `isAdmin`;
// the API enforces the same rules, hiding them only spares the user a 403.
import { createContext, useContext } from "react";

import type { User } from "./types";

export interface Auth {
  user: User;
  isAdmin: boolean;
  logout: () => void;
}

export const AuthContext = createContext<Auth | null>(null);

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth outside of AuthContext");
  return auth;
}
