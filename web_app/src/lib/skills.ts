export type SkillId = "general" | "budget_assistant" | "job_tracker" | "habit_tracker";

export interface Skill {
  id: SkillId;
  label: string;
  description: string;
}

export const SKILLS: Skill[] = [
  { id: "general", label: "General", description: "General purpose assistant" },
  { id: "budget_assistant", label: "Budget", description: "Track spending & budgets" },
  { id: "job_tracker", label: "Jobs", description: "Track job applications" },
  { id: "habit_tracker", label: "Habits", description: "Build and track habits" },
];
