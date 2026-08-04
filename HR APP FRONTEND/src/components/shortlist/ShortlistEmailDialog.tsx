import { Dispatch, SetStateAction } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Send } from "lucide-react";
import { EMAIL_TEMPLATES, renderEmailTemplate, type EmailTemplateKey } from "@/lib/emailTemplates";

export type ShortlistEmailDraft = {
  subject: string;
  body: string;
  candidateId: string;
  candidateName: string;
  toEmail: string;
  jobTitle?: string;
};

export function ShortlistEmailDialog({
  open,
  onOpenChange,
  emailDraft,
  setEmailDraft,
  sendingEmail,
  onSend,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  emailDraft: ShortlistEmailDraft;
  setEmailDraft: Dispatch<SetStateAction<ShortlistEmailDraft>>;
  sendingEmail: boolean;
  onSend: () => void;
}) {
  const applyTemplate = (key: EmailTemplateKey) => {
    const rendered = renderEmailTemplate(key, {
      candidateName: emailDraft.candidateName,
      jobTitle: emailDraft.jobTitle,
    });
    setEmailDraft((prev) => ({ ...prev, subject: rendered.subject, body: rendered.body }));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>AI-Drafted Email</DialogTitle>
          <DialogDescription>To: {emailDraft.toEmail} ({emailDraft.candidateName})</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label>Quick templates</Label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {EMAIL_TEMPLATES.map((template) => (
                <button
                  key={template.key}
                  type="button"
                  onClick={() => applyTemplate(template.key)}
                  className="rounded-xl border bg-background px-3 py-2 text-left transition-colors hover:bg-muted"
                >
                  <span className="block text-sm font-medium">{template.label}</span>
                  <span className="block text-xs text-muted-foreground">{template.description}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <Label>Subject</Label>
            <Input value={emailDraft.subject} onChange={e => setEmailDraft(prev => ({ ...prev, subject: e.target.value }))} />
          </div>
          <div className="space-y-2">
            <Label>Body</Label>
            <Textarea value={emailDraft.body} onChange={e => setEmailDraft(prev => ({ ...prev, body: e.target.value }))} className="min-h-[200px]" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={onSend} disabled={sendingEmail}>
            <Send className="h-4 w-4 mr-2" /> {sendingEmail ? 'Sending...' : 'Send Email'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
