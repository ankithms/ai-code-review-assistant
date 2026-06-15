import { useEffect, useState } from "react";
import { api } from "../services/api";

type PullRequest = {
  id: number;
  github_pr_id: number;
  title: string;
  repository: string;
  author: string;
};

export default function PullRequests() {
  const [prs, setPrs] = useState<PullRequest[]>([]);

  useEffect(() => {
    api.get("/pull-requests")
      .then((res) => {
        setPrs(res.data);
      });
  }, []);

  return (
    <div style={{ padding: "40px" }}>
      <h1>Pull Requests</h1>

      <table>
        <thead>
          <tr>
            <th>Title</th>
            <th>Repository</th>
            <th>Author</th>
          </tr>
        </thead>

        <tbody>
          {prs.map((pr) => (
            <tr key={pr.id}>
              <td>{pr.title}</td>
              <td>{pr.repository}</td>
              <td>{pr.author}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}