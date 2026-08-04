import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Progress } from "@/components/ui/progress";
import { Briefcase, FileText, User, Mail, CheckCircle2, XCircle } from "lucide-react";

interface Candidate {
  id: string;
  name: string;
  email: string;
  resume_score: number;
  tag: 'Strong' | 'Medium' | 'Reject';
  experience_years?: number;
}

export function ShortlistCandidateSheet({
  selectedCandidate,
  onClose,
  onViewProfile,
  onDraftEmail,
  draftingEmail,
}: {
  selectedCandidate: Candidate | null;
  onClose: () => void;
  onViewProfile: (id: string) => void;
  onDraftEmail: (candidate: Candidate, type: "invite" | "offer" | "reject") => void;
  draftingEmail: boolean;
}) {
  return (
    <Sheet open={!!selectedCandidate} onOpenChange={open => !open && onClose()}>
      <SheetContent className="sm:max-w-md w-[400px] border-l-black/[0.04] shadow-2xl p-0 flex flex-col bg-background/95 backdrop-blur-xl">
        {selectedCandidate && (
          <>
            <div className="p-6 border-b border-border bg-card">
              <SheetHeader className="text-left space-y-4">
                <div className="flex items-center justify-between">
                  <Badge variant={selectedCandidate.tag === 'Strong' ? 'default' : selectedCandidate.tag === 'Medium' ? 'secondary' : 'destructive'}>
                    {selectedCandidate.tag} Match
                  </Badge>
                  <span className="text-sm font-mono font-bold text-primary bg-primary/5 px-3 py-1 rounded-full">
                    {selectedCandidate.resume_score}% Fit
                  </span>
                </div>
                <div className="flex items-center gap-4">
                  <Avatar className="h-16 w-16 border-2 shadow-sm">
                    <AvatarFallback className="text-xl font-light">
                      {(selectedCandidate.name || '??').substring(0, 2).toUpperCase()}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <SheetTitle className="text-2xl font-bold tracking-tight">{selectedCandidate.name || 'Unknown'}</SheetTitle>
                    <SheetDescription className="text-sm">{selectedCandidate.email}</SheetDescription>
                  </div>
                </div>
              </SheetHeader>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-8">
              <div className="space-y-3">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                  <Briefcase className="h-4 w-4" /> Overview
                </h4>
                <div className="bg-card p-4 rounded-2xl border border-border shadow-sm space-y-3">
                  <div className="flex justify-between items-center text-sm">
                    <span className="text-muted-foreground">Experience</span>
                    <span className="font-medium">{selectedCandidate.experience_years ?? 'N/A'} Years</span>
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex justify-between items-center text-sm">
                      <span className="text-muted-foreground">Resume Score</span>
                      <span className="font-medium">{selectedCandidate.resume_score}%</span>
                    </div>
                    <Progress value={selectedCandidate.resume_score} className="h-1.5" />
                  </div>
                </div>
              </div>

              <div className="space-y-3">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                  <FileText className="h-4 w-4" /> Quick Actions
                </h4>
                <div className="grid gap-2">
                  <Button className="w-full justify-start rounded-xl h-12" variant="default" onClick={() => onViewProfile(selectedCandidate.id)}><User className="h-4 w-4 mr-3" /> View Full Profile</Button>
                  <Button className="w-full justify-start rounded-xl h-12" variant="outline" disabled={draftingEmail} onClick={() => onDraftEmail(selectedCandidate, 'invite')}><Mail className="h-4 w-4 mr-3" /> Draft Invite Email</Button>
                  <Button className="w-full justify-start rounded-xl h-12" variant="outline" disabled={draftingEmail} onClick={() => onDraftEmail(selectedCandidate, 'offer')}><CheckCircle2 className="h-4 w-4 mr-3" /> Generate Offer Letter</Button>
                  <Button className="w-full justify-start rounded-xl h-12 text-destructive hover:text-destructive hover:bg-destructive/5 border-destructive/20" variant="outline" disabled={draftingEmail} onClick={() => onDraftEmail(selectedCandidate, 'reject')}><XCircle className="h-4 w-4 mr-3" /> Reject Candidate</Button>
                </div>
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
