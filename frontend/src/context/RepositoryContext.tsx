import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "../services/api";
import { RepositoryContext, type Repository } from "./repository-context";

const STORAGE_KEY = "selectedRepositoryId";

export function RepositoryProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [selectedRepositoryId, setSelectedRepositoryIdState] =
    useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/repositories")
      .then((res) => {
        const nextRepositories = res.data as Repository[];
        setRepositories(nextRepositories);

        const storedRepositoryId = Number(
          window.localStorage.getItem(STORAGE_KEY)
        );
        const storedRepository = nextRepositories.find(
          (repository) => repository.id === storedRepositoryId
        );

        if (storedRepository) {
          setSelectedRepositoryIdState(storedRepository.id);
          return;
        }

        if (nextRepositories.length > 0) {
          setSelectedRepositoryIdState(nextRepositories[0].id);
          window.localStorage.setItem(
            STORAGE_KEY,
            String(nextRepositories[0].id)
          );
        }
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const setSelectedRepositoryId = (repositoryId: number) => {
    setSelectedRepositoryIdState(repositoryId);
    window.localStorage.setItem(STORAGE_KEY, String(repositoryId));
  };

  const selectedRepository = useMemo(
    () =>
      repositories.find((repository) => repository.id === selectedRepositoryId)
      ?? null,
    [repositories, selectedRepositoryId]
  );

  return (
    <RepositoryContext.Provider
      value={{
        repositories,
        selectedRepository,
        selectedRepositoryId,
        setSelectedRepositoryId,
        loading,
      }}
    >
      {children}
    </RepositoryContext.Provider>
  );
}
