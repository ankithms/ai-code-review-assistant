import { Link } from "react-router-dom";

export default function Navbar() {
  return (
    <nav
      style={{
        padding: "16px",
        borderBottom: "1px solid #ddd",
      }}
    >
      <Link to="/">Dashboard</Link>
      {" | "}
      <Link to="/reviews">Reviews</Link>
      {" | "}
      <Link to="/pull-requests">
        Pull Requests
        </Link>
    </nav>
  );
}