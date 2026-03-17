"use client";

export type SkillId = "general" | "budget_assistant" | "job_tracker" | "habit_tracker";

interface Skill {
  id: SkillId;
  label: string;
  description: string;
}

const SKILLS: Skill[] = [
  { id: "general", label: "General", description: "General purpose assistant" },
  { id: "budget_assistant", label: "Budget", description: "Track spending & budgets" },
  { id: "job_tracker", label: "Jobs", description: "Track job applications" },
  { id: "habit_tracker", label: "Habits", description: "Build and track habits" },
];

interface Props {
  selected: SkillId;
  onChange: (id: SkillId) => void;
}

export function SkillSelector({ selected, onChange }: Props) {
  return (
    <div style={{ padding: "16px 0" }}>
      <p style={{ fontSize: "11px", color: "var(--text-muted)", marginBottom: "8px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        Active Skill
      </p>
      {SKILLS.map((skill) => (
        <button
          key={skill.id}
          onClick={() => onChange(skill.id)}
          style={{
            width: "100%",
            textAlign: "left",
            padding: "10px 12px",
            borderRadius: "8px",
            marginBottom: "4px",
            background: selected === skill.id ? "rgba(124,106,247,0.15)" : "transparent",
            border: selected === skill.id ? "1px solid var(--accent)" : "1px solid transparent",
            color: selected === skill.id ? "var(--accent)" : "var(--text)",
            transition: "all 0.15s",
            cursor: "pointer",
          }}
        >
          <div style={{ fontWeight: 500, fontSize: "14px" }}>{skill.label}</div>
          <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "2px" }}>
            {skill.description}
          </div>
        </button>
      ))}
    </div>
  );
}
