import { createContext } from "react";

export type Repository = {
  id: number;
  full_name: string;
};

export type RepositoryContextValue = {
  repositories: Repository[];
  selectedRepository: Repository | null;
  selectedRepositoryId: number | null;
  setSelectedRepositoryId: (repositoryId: number) => void;
  loading: boolean;
};

export const RepositoryContext =
  createContext<RepositoryContextValue | null>(null);
