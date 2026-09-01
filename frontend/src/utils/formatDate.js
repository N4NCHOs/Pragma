const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** "Today, May 20 2026" / "Yesterday, May 19 2026" / "Monday, May 18 2026" */
export function formatNewsDate(isoString) {
  if (!isoString) return "Unknown date";

  const date = new Date(isoString);
  const now = new Date();

  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dayDiff = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);

  let label;
  if (dayDiff === 0) label = "Today";
  else if (dayDiff === 1) label = "Yesterday";
  else label = WEEKDAYS[date.getDay()];

  return `${label}, ${MONTHS[date.getMonth()]} ${date.getDate()} ${date.getFullYear()}`;
}

/** "2026-05-19 12:07PM UTC" — used on the News Detail header. */
export function formatNewsTimestamp(isoString) {
  if (!isoString) return "Unknown time";

  const date = new Date(isoString);
  const pad = (n) => String(n).padStart(2, "0");
  const hours24 = date.getUTCHours();
  const hours12 = ((hours24 + 11) % 12) + 1;
  const meridiem = hours24 < 12 ? "AM" : "PM";

  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ` +
    `${pad(hours12)}:${pad(date.getUTCMinutes())}${meridiem} UTC`
  );
}
