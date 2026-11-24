import i18n from "i18next";
import { initReactI18next } from "react-i18next";

export const en = {
  nav: { home: "Home", queue: "Submissions", clearance: "Duplicates", referrals: "Referrals", dashboards: "Dashboards",
    admin: "Administration", audit: "Audit explorer", profile: "Profile and sessions" },
  status: {
    received: "Received", in_review: "In review", needs_info: "Needs info", info_requested: "Info requested",
    ready_for_rating: "Ready for rating", rated: "Rated", quoted: "Quoted", declined: "Declined",
    decline_pending: "Decline pending", duplicate: "Duplicate", clearance_review: "Duplicate check",
    manual_review: "Manual queue", closed: "Closed",
  },
  outcome: { in_appetite: "In appetite", out_of_appetite: "Out of appetite", refer_risk_engineering: "Refer to RE", needs_info: "Needs info" },
  common: { offline: "You are offline. Changes will fail until the connection returns.", retry: "Retry", empty: "Nothing here yet" },
};

void i18n.use(initReactI18next).init({ resources: { en: { translation: en } }, lng: "en", fallbackLng: "en", interpolation: { escapeValue: false } });

export default i18n;
