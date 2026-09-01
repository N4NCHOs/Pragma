import { Outlet } from "react-router-dom";
import PageHeader from "../components/PageHeader.jsx";
import TabSwitcher from "../components/TabSwitcher.jsx";

export default function Dashboard() {
  return (
    <div className="mx-auto max-w-6xl px-6 pb-20 pt-16 sm:pt-24">
      <PageHeader />
      <div className="mt-8 mb-12 flex justify-center">
        <TabSwitcher />
      </div>
      <Outlet />
    </div>
  );
}
