import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  User, Building, Bell, Shield, Key, Globe, Eye, EyeOff, Lock,
  Mail, Server, Wifi, WifiOff, Trash2, CheckCircle2, AlertCircle, Loader2,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import api from "@/services/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

// ─── SMTP credential types ────────────────────────────────────────────────────
interface SmtpCredentials {
  smtp_server: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string;       // plain text — only in memory, never stored as-is
  smtp_password_hint?: string; // returned from backend (masked)
}

type SmtpStatus = "idle" | "saved" | "testing" | "ok" | "error";

// ─── Component ───────────────────────────────────────────────────────────────
export default function Settings() {
  const { user, refreshUser } = useAuth();
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("profile");

  // ── Profile / Company / Notifications state ────────────────────────────────
  const [profile, setProfile] = useState({
    // FIX: seed from user prop; refreshed via fetchProfile so it stays current
    name: user?.full_name || "",
    email: user?.email || "",
    company: "",
    role: "",
    companyBio: "",
    companyBlog: "",
    notifications: true,
  });

  // ── Change Password state ──────────────────────────────────────────────────
  const [isPwdOpen, setIsPwdOpen] = useState(false);
  const [pwdLoading, setPwdLoading] = useState(false);
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [pwdForm, setPwdForm] = useState({
    current_password: "",
    new_password: "",
    confirm_password: "",
  });

  // ── SMTP / Credentials state ───────────────────────────────────────────────
  const [smtpLoading, setSmtpLoading] = useState(false);
  const [smtpFetching, setSmtpFetching] = useState(false);
  const [smtpStatus, setSmtpStatus] = useState<SmtpStatus>("idle");
  const [smtpConfigured, setSmtpConfigured] = useState(false);
  const [showSmtpPwd, setShowSmtpPwd] = useState(false);
  const [testRecipient, setTestRecipient] = useState("");
  const [smtpErrorMsg, setSmtpErrorMsg] = useState("");
  const [smtpForm, setSmtpForm] = useState<SmtpCredentials>({
    smtp_server: "",
    smtp_port: 587,
    smtp_username: "",
    smtp_password: "",
  });
  const [smtpProvider, setSmtpProvider] = useState<string>("custom");
  const [savedPasswordHint, setSavedPasswordHint] = useState<string>("");

  // ── Fetch profile on mount ─────────────────────────────────────────────────
  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const { data } = await api.get("/auth/me");
        const prefs = data.preferences || {};
        const companyName = prefs.companyName || "";
        const companyBio = data.bio || prefs.companyBio || "";
        const companyWebsite = prefs.companyWebsite || "";
        setProfile({
          name: data.full_name || "",
          email: data.email || "",   // FIX: always sync from server
          company: companyName,
          role: prefs.role || "",
          companyBio,
          companyBlog: companyWebsite,
          notifications: prefs.notifications !== undefined ? prefs.notifications : true,
        });
      } catch {
        console.error("Failed to fetch profile");
      }
    };
    fetchProfile();
  }, []);

  // ── Fetch SMTP config when Credentials tab becomes active ──────────────────
  useEffect(() => {
    if (activeTab !== "credentials") return;
    const fetchSmtp = async () => {
      setSmtpFetching(true);
      try {
        const { data } = await api.get("/settings/smtp-credentials");
        const isConfigured = data.configured !== false;
        setSmtpForm(() => ({
          smtp_server: data.smtp_server || "smtp.gmail.com",
          smtp_port: data.smtp_port || 587,
          smtp_username: data.smtp_username,
          smtp_password: "", // never expose the real password client-side
        }));
        setSavedPasswordHint(data.smtp_password_hint || "");

        // Auto-detect provider for the dropdown
        if (data.smtp_server === "smtp.gmail.com") setSmtpProvider("google");
        else if (data.smtp_server === "smtp-mail.outlook.com") setSmtpProvider("outlook");
        else if (data.smtp_server === "smtp.mail.yahoo.com") setSmtpProvider("yahoo");
        else setSmtpProvider("custom");

        setSmtpConfigured(isConfigured);
        setSmtpStatus(isConfigured ? "saved" : "idle");
      } catch (err: any) {
        if (err?.response?.status === 404) {
          // No credentials saved yet — that's fine, show the empty form
          setSmtpConfigured(false);
          setSmtpStatus("idle");
        } else {
          toast.error("Failed to load SMTP credentials.");
        }
      } finally {
        setSmtpFetching(false);
      }
    };
    fetchSmtp();
  }, [activeTab]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleSave = async () => {
    setLoading(true);
    try {
      await api.put("/auth/me", {
        full_name: profile.name,
        bio: profile.companyBio,
        preferences: {
          companyName: profile.company,
          role: profile.role,
          companyBio: profile.companyBio,
          companyWebsite: profile.companyBlog,
          notifications: profile.notifications,
        },
      });
      await refreshUser();
      toast.success("Settings saved successfully!");
    } catch {
      toast.error("Failed to save settings. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleChangePassword = async () => {
    if (!pwdForm.current_password || !pwdForm.new_password || !pwdForm.confirm_password) {
      toast.error("Please fill in all password fields.");
      return;
    }
    if (pwdForm.new_password !== pwdForm.confirm_password) {
      toast.error("New passwords do not match.");
      return;
    }
    if (pwdForm.new_password.length < 8) {
      toast.error("New password must be at least 8 characters.");
      return;
    }
    setPwdLoading(true);
    try {
      await api.post("/auth/change-password", {
        current_password: pwdForm.current_password,
        new_password: pwdForm.new_password,
      });
      toast.success("Password changed successfully!");
      setIsPwdOpen(false);
      setPwdForm({ current_password: "", new_password: "", confirm_password: "" });
    } catch (error: any) {
      const msg = error?.response?.data?.detail || "Failed to change password.";
      toast.error(msg);
    } finally {
      setPwdLoading(false);
    }
  };

  const handleSaveSmtp = async () => {
    if (!smtpForm.smtp_username) {
      toast.error("Email / username is required.");
      return;
    }
    // Require a password only when creating a new config (not just editing server/port)
    if (!smtpConfigured && !smtpForm.smtp_password) {
      toast.error("Password is required.");
      return;
    }
    setSmtpLoading(true);
    try {
      const payload: any = {
        smtp_server: smtpForm.smtp_server,
        smtp_port: smtpForm.smtp_port,
        smtp_username: smtpForm.smtp_username,
      };
      // Only send password if the user typed one (blank = keep existing)
      if (smtpForm.smtp_password) {
        payload.smtp_password = smtpForm.smtp_password;
      } else if (!smtpConfigured) {
        toast.error("Password is required.");
        setSmtpLoading(false);
        return;
      } else {
        // Re-use existing stored password — backend requires the field, so we
        // must ask the user to re-enter if they want to change other fields.
        // For now require password if editing.
        toast.error("Please re-enter your password to save changes.");
        setSmtpLoading(false);
        return;
      }

      const { data } = await api.put("/settings/smtp-credentials", payload);
      setSavedPasswordHint(data.smtp_password_hint || "");
      setSmtpConfigured(true);
      setSmtpStatus("saved");
      setSmtpForm(prev => ({ ...prev, smtp_password: "" }));
      toast.success("SMTP credentials saved!");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Failed to save credentials.");
    } finally {
      setSmtpLoading(false);
    }
  };

  const handleTestSmtp = async () => {
    const recipient = (testRecipient || "").trim();
    if (!recipient) {
      toast.error("Test recipient email is required.");
      return;
    }
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(recipient)) {
      toast.error("Enter a valid recipient email address.");
      return;
    }

    setSmtpStatus("testing");
    setSmtpErrorMsg("");
    try {
      const { data } = await api.post("/settings/smtp-credentials/test", {
        test_recipient: recipient,
      });
      setSmtpStatus("ok");
      toast.success(data.message || "Test email sent!");
    } catch (err: any) {
      const msg = err?.response?.data?.detail || "SMTP test failed.";
      setSmtpStatus("error");
      setSmtpErrorMsg(msg);
      toast.error(msg);
    }
  };

  const handleDeleteSmtp = async () => {
    try {
      await api.delete("/settings/smtp-credentials");
      setSmtpConfigured(false);
      setSmtpStatus("idle");
      setSavedPasswordHint("");
      setSmtpForm({
        smtp_server: "smtp.gmail.com",
        smtp_port: 587,
        smtp_username: "",
        smtp_password: "",
      });
      toast.success("SMTP credentials removed.");
    } catch {
      toast.error("Failed to remove credentials.");
    }
  };

  // ─── Status badge helper ───────────────────────────────────────────────────
  const SmtpStatusBadge = () => {
    if (smtpStatus === "idle" && !smtpConfigured)
      return <Badge variant="outline" className="gap-1 text-muted-foreground"><WifiOff className="h-3 w-3" /> Not configured</Badge>;
    if (smtpStatus === "saved")
      return <Badge variant="outline" className="gap-1 text-blue-500 border-blue-500/30 bg-blue-500/10"><CheckCircle2 className="h-3 w-3" /> Saved</Badge>;
    if (smtpStatus === "testing")
      return <Badge variant="outline" className="gap-1 text-amber-500 border-amber-500/30 bg-amber-500/10"><Loader2 className="h-3 w-3 animate-spin" /> Testing…</Badge>;
    if (smtpStatus === "ok")
      return <Badge variant="outline" className="gap-1 text-green-500 border-green-500/30 bg-green-500/10"><Wifi className="h-3 w-3" /> Connected</Badge>;
    if (smtpStatus === "error")
      return <Badge variant="outline" className="gap-1 text-destructive border-destructive/30 bg-destructive/10"><AlertCircle className="h-3 w-3" /> Failed</Badge>;
    return null;
  };

  // ─── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-in fade-in duration-500">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Settings</h2>
        <p className="text-muted-foreground">Manage your account and company preferences.</p>
      </div>

      {/* Pill-Style Tab Navigation */}
      <div className="flex flex-wrap gap-2 mb-6 bg-muted/20 p-1.5 rounded-2xl w-fit border border-border/50">
        <Button variant={activeTab === "profile" ? "default" : "ghost"} className="rounded-xl px-5" onClick={() => setActiveTab("profile")}>
          <User className="h-4 w-4 mr-2" /> Profile
        </Button>
        <Button variant={activeTab === "company" ? "default" : "ghost"} className="rounded-xl px-5" onClick={() => setActiveTab("company")}>
          <Building className="h-4 w-4 mr-2" /> Company
        </Button>
        <Button variant={activeTab === "account" ? "default" : "ghost"} className="rounded-xl px-5" onClick={() => setActiveTab("account")}>
          <Shield className="h-4 w-4 mr-2" /> Account
        </Button>
        <Button variant={activeTab === "notifications" ? "default" : "ghost"} className="rounded-xl px-5" onClick={() => setActiveTab("notifications")}>
          <Bell className="h-4 w-4 mr-2" /> Notifications
        </Button>
        <Button variant={activeTab === "credentials" ? "default" : "ghost"} className="rounded-xl px-5" onClick={() => setActiveTab("credentials")}>
          <Mail className="h-4 w-4 mr-2" /> Credentials
        </Button>
      </div>

      <div className="grid gap-8">

        {/* ── Profile Tab ─────────────────────────────────────────────────── */}
        {activeTab === "profile" && (
          <Card className="animate-in slide-in-from-right-4 duration-300">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-xl">Personal Information</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Full Name</Label>
                  <Input value={profile.name} onChange={(e) => setProfile({ ...profile, name: e.target.value })} placeholder="e.g. Sarah Johnson" className="rounded-xl bg-muted/20" />
                </div>
                <div className="space-y-2">
                  <Label>Email Address</Label>
                  <Input value={profile.email} disabled className="rounded-xl bg-muted/50 cursor-not-allowed" />
                </div>
              </div>
            </CardContent>
            <CardFooter className="bg-muted/10 border-t justify-end p-4">
              <Button onClick={handleSave} disabled={loading} className="rounded-full px-6">
                {loading ? "Saving…" : "Save Changes"}
              </Button>
            </CardFooter>
          </Card>
        )}

        {/* ── Company Tab ─────────────────────────────────────────────────── */}
        {activeTab === "company" && (
          <Card className="animate-in slide-in-from-right-4 duration-300">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-xl">Company Details</CardTitle>
              <CardDescription>Design the public panel candidates see when they click "About Company".</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Company Name</Label>
                  <Input value={profile.company} onChange={(e) => setProfile({ ...profile, company: e.target.value })} placeholder="e.g. Acme Technologies" className="rounded-xl bg-muted/20 font-medium" />
                </div>
                <div className="space-y-2">
                  <Label>Your Role</Label>
                  <Input value={profile.role} onChange={(e) => setProfile({ ...profile, role: e.target.value })} placeholder="e.g. Senior Recruiter" className="rounded-xl bg-muted/20" />
                </div>
              </div>
              <div className="space-y-2">
                <Label>Company Website / Blog</Label>
                <div className="relative">
                  <Globe className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input value={profile.companyBlog} onChange={(e) => setProfile({ ...profile, companyBlog: e.target.value })} placeholder="https://..." className="pl-9 rounded-xl bg-muted/20" />
                </div>
              </div>
              <div className="space-y-2">
                <Label>About Company (Bio)</Label>
                <Textarea
                  value={profile.companyBio}
                  onChange={(e) => setProfile({ ...profile, companyBio: e.target.value })}
                  placeholder="Share your mission, culture, and vision with future candidates…"
                  className="rounded-xl bg-muted/20 min-h-[150px] resize-none leading-relaxed"
                />
              </div>
            </CardContent>
            <CardFooter className="bg-muted/10 border-t justify-end p-4">
              <Button onClick={handleSave} disabled={loading} className="rounded-full px-6">
                {loading ? "Publishing…" : "Publish Company Panel"}
              </Button>
            </CardFooter>
          </Card>
        )}

        {/* ── Account Tab ─────────────────────────────────────────────────── */}
        {activeTab === "account" && (
          <>
            <Card className="animate-in slide-in-from-right-4 duration-300">
              <CardHeader>
                <CardTitle className="text-xl">Security & Account</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between p-4 bg-muted/20 rounded-xl border border-border/50">
                  <div className="flex items-center gap-3">
                    <div className="h-9 w-9 flex items-center justify-center rounded-full bg-primary/10">
                      <Lock className="h-4 w-4 text-primary" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">Password</p>
                      <p className="text-xs text-muted-foreground">Change your account password</p>
                    </div>
                  </div>
                  <Button variant="outline" className="rounded-xl" onClick={() => setIsPwdOpen(true)}>
                    <Key className="h-4 w-4 mr-2" /> Change Password
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Change Password Dialog */}
            <Dialog open={isPwdOpen} onOpenChange={(open) => {
              setIsPwdOpen(open);
              if (!open) setPwdForm({ current_password: "", new_password: "", confirm_password: "" });
            }}>
              <DialogContent className="sm:max-w-[420px] rounded-2xl">
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2"><Lock className="h-5 w-5 text-primary" /> Change Password</DialogTitle>
                  <DialogDescription>Enter your current password, then choose a new one.</DialogDescription>
                </DialogHeader>
                <div className="space-y-4 py-2">
                  {[
                    { label: "Current Password", key: "current_password", show: showCurrent, setShow: setShowCurrent },
                    { label: "New Password", key: "new_password", show: showNew, setShow: setShowNew },
                    { label: "Confirm New Password", key: "confirm_password", show: showConfirm, setShow: setShowConfirm },
                  ].map(({ label, key, show, setShow }) => (
                    <div key={key} className="space-y-2">
                      <Label>{label}</Label>
                      <div className="relative">
                        <Input
                          type={show ? "text" : "password"}
                          value={(pwdForm as any)[key]}
                          onChange={(e) => setPwdForm({ ...pwdForm, [key]: e.target.value })}
                          className={`rounded-xl bg-muted/20 pr-10 ${key === "confirm_password" && pwdForm.confirm_password && pwdForm.new_password !== pwdForm.confirm_password ? "border-destructive" : ""}`}
                          placeholder={key === "new_password" ? "Min. 8 characters" : ""}
                        />
                        <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setShow((v: boolean) => !v)}>
                          {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                      {key === "confirm_password" && pwdForm.confirm_password && pwdForm.new_password !== pwdForm.confirm_password && (
                        <p className="text-xs text-destructive">Passwords do not match</p>
                      )}
                    </div>
                  ))}
                </div>
                <DialogFooter>
                  <Button variant="ghost" onClick={() => setIsPwdOpen(false)} className="rounded-full">Cancel</Button>
                  <Button onClick={handleChangePassword} disabled={pwdLoading} className="rounded-full px-6">
                    {pwdLoading ? "Updating…" : "Update Password"}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </>
        )}

        {/* ── Notifications Tab ───────────────────────────────────────────── */}
        {activeTab === "notifications" && (
          <Card className="animate-in slide-in-from-right-4 duration-300">
            <CardHeader>
              <CardTitle>Preferences</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label>Email Alerts</Label>
                  <p className="text-xs text-muted-foreground">Receive updates on candidates.</p>
                </div>
                <Switch checked={profile.notifications} onCheckedChange={(c) => setProfile({ ...profile, notifications: c })} />
              </div>
            </CardContent>
            <CardFooter className="bg-muted/10 border-t justify-end p-4">
              <Button onClick={handleSave} disabled={loading} className="rounded-full px-6">
                {loading ? "Saving…" : "Save Preferences"}
              </Button>
            </CardFooter>
          </Card>
        )}

        {/* ── Credentials Tab ─────────────────────────────────────────────── */}
        {activeTab === "credentials" && (
          <div className="animate-in slide-in-from-right-4 duration-300 space-y-5">

            {/* Header card */}
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 flex items-center justify-center rounded-full bg-primary/10">
                      <Mail className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-xl">SMTP Credentials</CardTitle>
                      <CardDescription>Configure outbound email delivery for candidate notifications and quiz invitations.</CardDescription>
                    </div>
                  </div>
                  <SmtpStatusBadge />
                </div>
              </CardHeader>

              {smtpFetching ? (
                <CardContent className="py-10 flex justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </CardContent>
              ) : (
                <>
                  <CardContent className="space-y-5">
                    {/* Provider Selection */}
                    <div className="space-y-4">
                      <div className="space-y-2">
                        <Label>Email Provider</Label>
                        <Select
                          value={smtpProvider}
                          onValueChange={(val) => {
                            setSmtpProvider(val);
                            if (val === "google") {
                              setSmtpForm({ ...smtpForm, smtp_server: "smtp.gmail.com", smtp_port: 587 });
                            } else if (val === "outlook") {
                              setSmtpForm({ ...smtpForm, smtp_server: "smtp-mail.outlook.com", smtp_port: 587 });
                            } else if (val === "yahoo") {
                              setSmtpForm({ ...smtpForm, smtp_server: "smtp.mail.yahoo.com", smtp_port: 587 });
                            } else {
                              setSmtpForm({ ...smtpForm, smtp_server: "", smtp_port: 587 });
                            }
                          }}
                        >
                          <SelectTrigger className="w-full bg-muted/20">
                            <SelectValue placeholder="Select a provider" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="google">Google / Gmail</SelectItem>
                            <SelectItem value="outlook">Microsoft Outlook</SelectItem>
                            <SelectItem value="yahoo">Yahoo Mail</SelectItem>
                            <SelectItem value="custom">Custom Provider</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      <div className="grid grid-cols-[1fr_120px] gap-4">
                        <div className="space-y-2">
                          <Label className="flex items-center gap-1.5"><Server className="h-3.5 w-3.5 text-muted-foreground" /> SMTP Server</Label>
                          <Input
                            value={smtpForm.smtp_server}
                            onChange={(e) => setSmtpForm({ ...smtpForm, smtp_server: e.target.value })}
                            placeholder="e.g. mail.yourdomain.com"
                            className="rounded-xl bg-muted/20"
                          />
                        </div>
                        <div className="space-y-2">
                          <Label>Port</Label>
                          <Input
                            type="number"
                            value={smtpForm.smtp_port}
                            onChange={(e) => setSmtpForm({ ...smtpForm, smtp_port: Number(e.target.value) })}
                            className="rounded-xl bg-muted/20"
                          />
                        </div>
                      </div>
                    </div>

                    {/* Username */}
                    <div className="space-y-2">
                      <Label className="flex items-center gap-1.5"><Mail className="h-3.5 w-3.5 text-muted-foreground" /> Email / Username</Label>
                      <Input
                        value={smtpForm.smtp_username}
                        onChange={(e) => setSmtpForm({ ...smtpForm, smtp_username: e.target.value })}
                        className="rounded-xl bg-muted/20"
                      />
                    </div>

                    {/* Password */}
                    <div className="space-y-2">
                      <Label className="flex items-center gap-1.5"><Lock className="h-3.5 w-3.5 text-muted-foreground" /> Password / App Password</Label>
                      <div className="relative">
                        <Input
                          type={showSmtpPwd ? "text" : "password"}
                          value={smtpForm.smtp_password}
                          onChange={(e) => setSmtpForm({ ...smtpForm, smtp_password: e.target.value })}
                          placeholder={smtpConfigured && savedPasswordHint ? savedPasswordHint : "Enter password or App Password"}
                          className="rounded-xl bg-muted/20 pr-10"
                        />
                        <button
                          type="button"
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          onClick={() => setShowSmtpPwd(v => !v)}
                        >
                          {showSmtpPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                      {smtpConfigured && (
                        <p className="text-xs text-muted-foreground">
                          A password is already saved ({savedPasswordHint}). Re-enter to update it.
                        </p>
                      )}
                    </div>

                    {/* Provider hint */}
                    <div className="rounded-xl bg-blue-500/5 border border-blue-500/20 p-3.5 text-xs text-blue-600 dark:text-blue-400 space-y-1">
                      <p className="font-semibold">How to connect your provider (Outlook, Gmail, etc.)</p>
                      <p>Enter your provider's SMTP server (e.g., <code>smtp-mail.outlook.com</code> or <code>smtp.gmail.com</code>). For most providers, you must generate an <strong>App Password</strong> in your security settings to use here instead of your normal password.</p>
                    </div>

                    {/* Error message */}
                    {smtpStatus === "error" && smtpErrorMsg && (
                      <div className="rounded-xl bg-destructive/5 border border-destructive/20 p-3.5 flex items-start gap-2 text-xs text-destructive">
                        <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                        <span>{smtpErrorMsg}</span>
                      </div>
                    )}
                  </CardContent>

                  <CardFooter className="bg-muted/10 border-t p-4 flex items-center justify-between gap-3 flex-wrap">
                    {/* Left side: delete */}
                    <div>
                      {smtpConfigured && (
                        <Button variant="ghost" size="sm" className="rounded-xl text-muted-foreground hover:text-destructive gap-1.5" onClick={handleDeleteSmtp}>
                          <Trash2 className="h-3.5 w-3.5" /> Remove credentials
                        </Button>
                      )}
                    </div>
                    {/* Right side: test + save */}
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        className="rounded-xl gap-2"
                        disabled={!smtpConfigured || smtpStatus === "testing"}
                        onClick={handleTestSmtp}
                      >
                        {smtpStatus === "testing"
                          ? <><Loader2 className="h-4 w-4 animate-spin" /> Testing…</>
                          : <><Wifi className="h-4 w-4" /> Test Connection</>
                        }
                      </Button>
                      <Button className="rounded-full px-6 gap-2" onClick={handleSaveSmtp} disabled={smtpLoading}>
                        {smtpLoading
                          ? <><Loader2 className="h-4 w-4 animate-spin" /> Saving…</>
                          : "Save Credentials"
                        }
                      </Button>
                    </div>
                  </CardFooter>
                </>
              )}
            </Card>

            {/* Test email helper */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-primary" /> Send Test Email
                </CardTitle>
                <CardDescription>Verify your configuration by sending a test message.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="test-recipient">Test Recipient Email</Label>
                  <Input
                    id="test-recipient"
                    value={testRecipient}
                    onChange={(e) => setTestRecipient(e.target.value)}
                    placeholder="Enter email to receive test message"
                    className="rounded-xl bg-muted/20"
                  />
                </div>
                {!smtpConfigured && (
                  <p className="text-xs text-muted-foreground">
                    Save credentials first to enable test email sending.
                  </p>
                )}
              </CardContent>
              <CardFooter className="bg-muted/10 border-t p-4 justify-end">
                <Button
                  className="rounded-full px-6 gap-2"
                  onClick={handleTestSmtp}
                  disabled={!smtpConfigured || smtpStatus === "testing"}
                >
                  {smtpStatus === "testing"
                    ? <><Loader2 className="h-4 w-4 animate-spin" /> Sending…</>
                    : <><Mail className="h-4 w-4" /> Send Test</>
                  }
                </Button>
              </CardFooter>
            </Card>
          </div>
        )}

      </div>
    </div>
  );
}
