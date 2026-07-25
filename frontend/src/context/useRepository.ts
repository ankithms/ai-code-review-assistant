import { useContext } from "react";
import { RepositoryContext } from "./repository-context";

export function useRepository() {
  const context = useContext(RepositoryContext);

  if (context === null) {
    throw new Error("useRepository must be used inside RepositoryProvider");
  }

  return context;
}
