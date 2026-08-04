import React, { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { AlertCircle, Loader2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import {
  CandidateKycMagicContext,
  KycDocType,
  getKycMagicContext,
  uploadKycWithMagicLink,
} from "@/services/candidatePortal";

const DOC_LABELS: Record<KycDocType, string> = {
  aadhaar: "Aadhaar Card (masked preferred)",
  pan: "PAN Card",
  employment_proof: "Previous Employment Proof",
  passport: "Passport",
  driving_license: "Driving License",
  salary_slip: "Salary Slip",
  offer_letter: "Offer Letter",
};

export default function CandidateKycUpload() {
  const [searchParams] = useSearchParams();
  const token = (searchParams.get("token") || "").trim();

  const [context, setContext] = useState<CandidateKycMagicContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [consentGiven, setConsentGiven] = useState(false);
  const [aadhaarMaskedConfirmed, setAadhaarMaskedConfirmed] = useState(false);
  const [filesByType, setFilesByType] = useState<Partial<Record<KycDocType, File>>>({});

  React.useEffect(() => {
    const run = async () => {
      if (!token) {
        setLoading(false);
        return;
      }
      try {
        const next = await getKycMagicContext(token);
        setContext(next);
      } catch (err: any) {
        toast.error(err?.response?.data?.detail || "This KYC link is invalid or expired.");
      } finally {
        setLoading(false);
      }
    };
    void run();
  }, [token]);

  const mandatoryMissing = useMemo(() => {
    if (!context) return [];
    return context.mandatory_doc_types.filter((docType) => !filesByType[docType]);
  }, [context, filesByType]);

  const selectedDocTypes = useMemo(
    () => Object.entries(filesByType).filter(([, file]) => !!file).map(([docType]) => docType as KycDocType),
    [filesByType],
  );

  const handleSubmit = async () => {
    if (!context || !token) return;
    if (!consentGiven) {
      toast.error("Please provide consent before uploading.");
      return;
    }
    if (mandatoryMissing.length > 0) {
      toast.error(`Please upload mandatory documents: ${mandatoryMissing.join(", ")}`);
      return;
    }
    if (context.require_masked_aadhaar && !aadhaarMaskedConfirmed) {
      toast.error("Please confirm Aadhaar is masked before upload.");
      return;
    }
    const files = selectedDocTypes
      .map((docType) => filesByType[docType])
      .filter((file): file is File => !!file);
    if (files.length === 0) {
      toast.error("Please upload at least one document.");
      return;
    }

    setSubmitting(true);
    try {
      const result = await uploadKycWithMagicLink({
        token,
        consentGiven: true,
        consentPurposeAck: context.purpose,
        consentAccessAck: context.access_scope,
        consentRetentionAckDays: context.retention_days,
        aadhaarMaskedConfirmed,
        docTypes: selectedDocTypes,
        files,
      });
      toast.success(result.message);
      setDone(true);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "KYC upload failed.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!token || !context) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <Card className="max-w-lg w-full">
          <CardHeader>
            <CardTitle>Secure KYC Link Unavailable</CardTitle>
            <CardDescription>This upload link is invalid, expired, or already used.</CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <Card className="max-w-lg w-full">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-emerald-600" />
              Upload Complete
            </CardTitle>
            <CardDescription>Your KYC documents were submitted successfully.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              This one-time link is now closed. Documents will be retained for{" "}
              <strong>{context.retention_days} days</strong>
              {context.legal_hold_required ? " (or longer if legally required)." : "."}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-muted/20 py-10 px-4">
      <div className="max-w-3xl mx-auto">
        <Card>
          <CardHeader>
            <CardTitle>Secure KYC Upload</CardTitle>
            <CardDescription>
              Final verification stage upload. This is a one-time link that expires on{" "}
              {new Date(context.expires_at).toLocaleString("en-GB")}.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="rounded-lg border p-4 bg-muted/20 space-y-2 text-sm">
              <p><strong>Purpose:</strong> {context.purpose}</p>
              <p><strong>Who can access:</strong> {context.access_scope}</p>
              <p><strong>Retention:</strong> {context.retention_days} days{context.legal_hold_required ? " (legal hold may apply)" : ""}</p>
            </div>

            <div className="space-y-4">
              {context.allowed_doc_types.map((docType) => (
                <div key={docType} className="rounded-lg border p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <Label className="font-medium">{DOC_LABELS[docType]}</Label>
                    {context.mandatory_doc_types.includes(docType) ? <Badge>Mandatory</Badge> : <Badge variant="secondary">Optional</Badge>}
                  </div>
                  <Input
                    type="file"
                    accept=".pdf,.png,.jpg,.jpeg,.webp"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      setFilesByType((prev) => ({ ...prev, [docType]: file || undefined }));
                    }}
                  />
                  {filesByType[docType] ? (
                    <p className="text-xs text-muted-foreground">Selected: {filesByType[docType]?.name}</p>
                  ) : null}
                </div>
              ))}
            </div>

            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-start gap-3">
                <Switch id="consent" checked={consentGiven} onCheckedChange={(v) => setConsentGiven(!!v)} />
                <Label htmlFor="consent" className="text-sm leading-relaxed">
                  I consent to upload these documents for the stated purpose, access scope, and retention period.
                </Label>
              </div>
              {context.require_masked_aadhaar ? (
                <div className="flex items-start gap-3">
                  <Switch
                    id="masked-aadhaar"
                    checked={aadhaarMaskedConfirmed}
                    onCheckedChange={(v) => setAadhaarMaskedConfirmed(!!v)}
                  />
                  <Label htmlFor="masked-aadhaar" className="text-sm leading-relaxed">
                    I confirm the Aadhaar copy uploaded is masked (first 8 digits hidden), unless legally required otherwise.
                  </Label>
                </div>
              ) : null}
            </div>

            {mandatoryMissing.length > 0 ? (
              <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-start gap-2">
                <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                Missing mandatory files: {mandatoryMissing.join(", ")}
              </div>
            ) : null}
          </CardContent>
          <CardFooter className="justify-end">
            <Button onClick={handleSubmit} disabled={submitting || !consentGiven}>
              {submitting ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Submit Secure Upload
            </Button>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}
