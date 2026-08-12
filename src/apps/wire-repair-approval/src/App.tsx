import { useCallback, useState } from "react";
import ApprovalForm from "./components/ApprovalForm";

export default function App() {
  const [darkTheme, setDarkTheme] = useState(false);
  const initializeTheme = useCallback((dark: boolean) => {
    setDarkTheme(dark);
    document.body.dataset.theme = dark ? "dark" : "light";
  }, []);

  return <main className={darkTheme ? "dark" : "light"}><ApprovalForm onInitTheme={initializeTheme} /></main>;
}
