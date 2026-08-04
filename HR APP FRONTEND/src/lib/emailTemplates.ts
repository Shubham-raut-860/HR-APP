export type EmailTemplateKey =
  | "interview_invite"
  | "assessment_followup"
  | "shortlist_update"
  | "courteous_rejection";

export type EmailTemplateContext = {
  candidateName?: string;
  jobTitle?: string;
  recruiterName?: string;
  companyName?: string;
};

export type RenderedEmailTemplate = {
  subject: string;
  body: string;
};

export const EMAIL_TEMPLATES: Array<{
  key: EmailTemplateKey;
  label: string;
  description: string;
}> = [
  {
    key: "interview_invite",
    label: "Interview invite",
    description: "Invite a shortlisted candidate to the next conversation.",
  },
  {
    key: "assessment_followup",
    label: "Assessment follow-up",
    description: "Share quiz or assessment next steps clearly.",
  },
  {
    key: "shortlist_update",
    label: "Shortlist update",
    description: "Confirm that the candidate has moved forward.",
  },
  {
    key: "courteous_rejection",
    label: "Polite rejection",
    description: "Close the loop respectfully without over-sharing.",
  },
];

const firstName = (name?: string) => {
  const trimmed = name?.trim();
  return trimmed ? trimmed.split(/\s+/)[0] : "there";
};

const roleText = (jobTitle?: string) => jobTitle?.trim() || "the role";

const signoff = (companyName?: string, recruiterName?: string) => {
  const company = companyName?.trim();
  const recruiter = recruiterName?.trim();
  if (recruiter && company) return `${recruiter}\n${company}`;
  if (recruiter) return recruiter;
  if (company) return `${company} Hiring Team`;
  return "Hiring Team";
};

export function renderEmailTemplate(
  key: EmailTemplateKey,
  context: EmailTemplateContext = {}
): RenderedEmailTemplate {
  const name = firstName(context.candidateName);
  const role = roleText(context.jobTitle);
  const closing = signoff(context.companyName, context.recruiterName);

  switch (key) {
    case "assessment_followup":
      return {
        subject: `Next step for ${role}: assessment details`,
        body:
          `Hi ${name},\n\n` +
          `Thank you for your interest in ${role}. We would like you to complete the assessment step so we can better understand your fit for the position.\n\n` +
          `Please use the assessment link shared with you and complete it before the stated deadline. If anything is unclear, reply to this email and we will help.\n\n` +
          `Best regards,\n${closing}`,
      };
    case "shortlist_update":
      return {
        subject: `You have been shortlisted for ${role}`,
        body:
          `Hi ${name},\n\n` +
          `Good news. Your profile has been shortlisted for ${role}. Our team is reviewing the next step and will share the interview or assessment details shortly.\n\n` +
          `Thank you for taking the time to apply.\n\n` +
          `Best regards,\n${closing}`,
      };
    case "courteous_rejection":
      return {
        subject: `Update on your application for ${role}`,
        body:
          `Hi ${name},\n\n` +
          `Thank you for applying for ${role}. After reviewing your profile, we will not be moving forward for this position at this time.\n\n` +
          `We appreciate your interest and wish you the best in your job search.\n\n` +
          `Best regards,\n${closing}`,
      };
    case "interview_invite":
    default:
      return {
        subject: `Interview invitation for ${role}`,
        body:
          `Hi ${name},\n\n` +
          `Thank you for applying for ${role}. We were impressed by your profile and would like to invite you to the next interview round.\n\n` +
          `Please reply with a few time slots that work for you over the next few days, and we will confirm the schedule.\n\n` +
          `Best regards,\n${closing}`,
      };
  }
}
