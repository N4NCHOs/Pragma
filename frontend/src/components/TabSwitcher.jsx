import { NavLink } from "react-router-dom";

const TAB_CLASS = ({ isActive }) =>
  `rounded-full px-5 py-2 text-sm font-medium transition-colors duration-200 ${
    isActive ? "bg-surface-hover text-text" : "text-text-muted hover:text-text"
  }`;

export default function TabSwitcher() {
  return (
    <nav className="mx-auto flex w-fit gap-1 rounded-full border border-border bg-surface p-1 backdrop-blur-sm">
      <NavLink to="/" end className={TAB_CLASS}>
        Top 10 Assets
      </NavLink>
      <NavLink to="/news" className={TAB_CLASS}>
        Latest News
      </NavLink>
    </nav>
  );
}
