unit uWaptRes;

{$mode objfpc}{$H+}

interface

uses
  Classes, SysUtils, DefaultTranslator;

resourcestring

  { --- MESSAGES DANS LA CONSOLE WAPT --- }
  { Messages dans uwaptconsole.pas }
  rsFatalError = 'Failed to retrieve task.'; // '... Impossible de récupérer l''action.';
  rsInstalling = 'Installing %s...';
  rsDefineWaptdevPath = 'Please select a directory on your package development host before editing a package bundle.'; //'Veuillez définir un répertoire de développement pour pouvoir éditer un paquet groupe.'

  rsPublicKeyGenSuccess = 'Key %s has been successfully created.';
  rsPublicKeyGenFailure = 'The generation of the public key has failed.';
  rsPublicKeyGenError = 'Error during key generation : %s';

  rsCreationInProgress = 'Creation in progress.'; //'Création en cours'
  rsProgressTitle = 'Started uploading to WAPT server...';  // TODO more meaningful var name
  rsWaptSetupUploadSuccess = 'WAPT agent successfully created and uploaded to the repository : %s';
  rsWaptUploadError = 'Error while uploading WAPT agent to the repository : %s';
  rsWaptSetupError = 'Error while creating agent : %s';

  rsForcedUninstallPackages = 'Selection of packages to force-remove from the hosts'; // 'Choix des paquets à forcer à désintaller sur les postes sélectionnés'; TODO
  rsDependencies = 'Selection of packages to add to the hosts as dependencies'; // 'Choix des paquets à ajouter en dépendance aux postes sélectionnés';
  rsNbModifiedHosts = '%s hosts affected.';
  rsTaskCanceled = 'Task canceled.';
  rsFailedToCancel = 'Could not cancel : %s.';

  rsIncorrectPassword = 'Incorrect password.';
  rsPasswordChangeSuccess = 'Password successfully updated !';
  rsPasswordChangeError = 'Error : %s';

  rsWaptAgentUploadSuccess = 'Successfully uploaded WAPT agent !';
  rsWaptAgentUploadError = 'Error while uploading WAPT agent : %s';
  rsWaptAgentSetupSuccess = 'waptagent.exe successfully created : %s';
  rsWaptAgentSetupError = 'Error while creating waptagent.exe: %s';

  rsConfirmRmOnePackage = 'Are you sure you want to remove this package from the server ?';
  rsConfirmRmMultiplePackages = 'Are you sure you want to remove the selected packages from the server ?';
  rsConfirmRmPackageCaption = 'Confirm removal';
  rsDeletionInProgress = 'Removing packages...';
  rsDeletingElement = 'Removing %s';
  rsUpdatingPackageList = 'Updating package list';
  rsDisplaying = 'Displaying';
  rsConfirmDeletion = 'Confirm removal';  // Duplicate of rsConfirmRmPackageCaption

  rsConfirmCaption = 'Confirm';

  rsConfirmHostForgetsPackages = 'Are you sure you want to forget %s packages from host %s ?';
  rsForgetPackageError = 'Error while forgetting package %s: %s';

  rsPrivateKeyDoesntExist = 'Private key doesn''t exist : %s';

  rsConfirmImportCaption = 'Confirm import';
  rsConfirmImport = 'Are you sure you want to import'#13#10'%s'#13#10' to your repository ?';
  rsImportingFile = 'Importing %s';
  rsUploadingPackagesToWaptSrv = 'Uploading %s packages to WAPT server...';
  rsSuccessfullyImported = '%s successfully imported.';
  rsFailedImport = 'Error during import.';

  rsConfirmRmPackagesFromHost = 'Are you sure you want to remove %s package(s) from the selected host(s) %s ?';
  rsPackageRemoveError = 'Error while removing package %s: %s';

  rsReallowPackagesOnHost = 'Selection of package(s) to remove from conflict list'; // 'Choix des paquets à réautoriser sur les postes sélectionnés';
  rsRmBundleFromHosts = 'Selection of package bundles for removing from the selected hosts';
  rsNoBundle = 'There is no package bundle.'; // 'Il n''y a aucun groupe.'; TODO : pas assez explicite ?

  rsWaptClientUpdateOnHosts = 'Updating WAPT client on the hosts';

  rsConfirmRmHostsFromList = 'Are you sure you want to remove %s hosts from the list ?';

  rsUninstallingPackage = 'Uninstalling %s...';

  rsCanceledByUser = 'Task %s has been canceled by the user';

  { Messages dans wapt-get/waptcommon.pas }
  rsInnoSetupUnavailable = 'Innosetup is unavailable (path : %s), please install it first.';
  rsUndefWaptSrvInIni = 'wapt_server is not defined in your %s ini file';
  rsDlStoppedByUser = 'Download stopped by the user';
  rsCertificateCopyFailure = 'Couldn''t copy certificate %s to %s.';

  { Messages dans uVisCreateKey }
  rsInputKeyName = 'Please input a key name.'; // 'Veuillez rentrer un nom de clé'; // TODO
  rsKeyAlreadyExists = 'Key %s already exists, please pick another name.';

  { Messages dans uVisEditPackage.pas }
  rsEditBundle = 'Edit package bundle.';
  rsEdPackage = 'Package bundle';
  rsPackagesNeededCaption = 'Packages needed in package bundle';

  rsEditHostCaption = 'Edit host';
  rsUpgradingHost = 'Upgrade triggered on the remote host.'; // Mise à jour lancée
  rsUpgradeHostError = 'Failed to trigger upgrade : %s';

  rsSaveMods = 'Save changes ?';
  rsUploading = 'Uploading';
  rsPackageCreationError = 'Error while creating package : %s';
  rsHostConfigEditCaption = 'Edit host configuration';
  rsPackagesNeededOnHostCaption = 'Packages needed on host';

  rsDownloading = 'Downloading';
  rsBundleConfigEditCaption = 'Edit package bundle configuration';
  rsDlCanceled = 'Download canceled.';
  rsIgnoredPackages = 'Warning : couldn''t find package(s) %s ; ignoring them.';
  rsIgnoredConfictingPackages = 'Warning : couldn''t find package(s) %s ; conflicting package(s) have been ignored.'; // TODO

  { Messages dans uVisEditPackage.pas }
  rsInputPubKeyPath = 'Please input path to public key';
  rsInvalidWaptSetupDir = 'WAPTsetup directory is not valid : %s'; // 'Le répertoire pour sauvegarder waptsetup n''est pas valide: %s';

  { Messages dans uVisChangePassword.pas }
  rsDiffPwError = 'Passwords do not match.';
  rsEmptyNewPwError = 'New password must not be empty.';
  rsEmptyOldPwError = 'Old password must not be empty.';
  rsIncorrectOldPwError = 'Old password is incorrect.';

  { Messages dans uVisApropos }
  rsVersion = 'Waptconsole version : %s'#13#10'Wapt-get version: %s';

  { Messages dans uVisApropos }
  rsUrl = 'Url : %s';
  rsPackageDuplicateConfirmCaption = 'Confirm duplication of package';
  rsPackageDuplicateConfirm = 'Are you sure you want to duplicate the package(s)'#13#10'%s'#13#10' into your repository ?'; // TODO : 'in' vs 'into' ?
  rsDownloadingPackage = 'Package(s) %s is being downloaded.';
  rsDuplicating = 'Package(s) %s is being duplicated.';
  rsDuplicateSuccess = 'Package(s) %s successfully duplicated.';
  rsDuplicateFailure = 'Error while duplicating the package(s).';


  { --- MESSAGES DANS LE TRAY WAPT --- }
  rsUpdatesAvailableFor = 'Available updates for : '#13#10;
  rsErrorFor = 'Error for %s';
  rsError = 'Error';
  rsTaskStarted = '%s started';
  rsTaskDone = '%s done'#13#10'%s';
  rsCanceling = 'Canceling %s';
  rsNoTaskCanceled = 'No task canceled';
  rsPackageConfigDone = 'Done configuring packages for the current user session';
  rsPackageConfigError = 'Error while configuring packages for the current user session';
  rsWaptServiceTerminated = 'WAPTService terminated';
  rsChecking = 'Checking...';
  rsErrorWhileChecking = 'Error while checking...';


  { --- MESSAGES DANS WAPTSERVER - PostConf --- }
  rsWaptServiceStopping = 'Waptservice stopping';
  rsUpdatingPackageIndex = 'Updating package index';
  rsReplacingTIScertificate = 'Deleting TIS certificate and copying new certificate';
  rsSettingServerPassword = 'Setting up server password';
  rsOpeningFirewall = 'Opening firewall for WaptServer';
  rsRestartingWaptServer = 'Redémarrage service waptserver';
  rsRestartingWaptService = 'Redémarrage waptservice';
  rsRegisteringHostOnServer = 'Registering host on server';
  rsUpdatingLocalPackages = 'Updating local packages';
  rsConfirm = 'Confirm';
  rsConfirmCancelPostConfig = 'Are you sure you want to cancel configuring WAPT server ?';
  rsInvalidDNS = 'Invalid DNS';
  rsInvalidDNSfallback = 'This DNS name is not valid, would you like to use the IP address instead ?';


  { --- MESSAGES DANS WAPTGET --- }
  rsWinterruptReceived = 'W: interrupt received, killing server…';
  rsStopListening = 'Stop listening to events';
  rsOptRepo = ' -r --repo : URL of dependencies libs';
  rsWaptUpgrade = ' waptupgrade : upgrade wapt-get.exe and database';
  rsWin32exeWrapper = 'Win32 Exe wrapper: %s %s';
  rsWaptGetUpgrade = 'WAPT-GET Upgrade using repository at %s';
  rsDNSserver = 'DNS Server : %s';
  rsDNSdomain = 'DNS Domain : %s';
  rsMainRepoURL = 'Main repo url: %s';
  rsSRV = 'SRV: %s';
  rsCNAME = 'CNAME: %s';
  rsLongtaskError = 'Error launching longtask: %s';
  rsTaskListError = 'Error getting task list: %s';
  rsRunningTask = 'Running task %d: %s, status:%s';
  rsNoRunningTask = 'No running tasks';
  rsPending = 'Pending : ';
  rsErrorCanceling = 'Error cancelling: %s';
  rsCanceledTask = 'Cancelled %s';
  rsErrorLaunchingUpdate = 'Error launching update: %s';
  rsErrorWithMessage = 'Error : %s';
  rsErrorLaunchingUpgrade = 'Error launching upgrade: %s';
  rsCanceled = 'canceled';
  rsUsage = 'Usage: %s -h';
  rsInstallOn = '  install on c:\wapt : --setup -s';
  rsCompletionProgress = '%s : %.0f%% completed';

implementation

end.
