unit dmwaptpython;

{$mode objfpc}{$H+}

interface

uses
  Classes, SysUtils, FileUtil, PythonEngine, PythonGUIInputOutput, VarPyth,
  vte_json, superobject, fpjson, jsonparser, DefaultTranslator;

type

  { TDMPython }

  TDMPython = class(TDataModule)
    PythonEng: TPythonEngine;
    PythonOutput: TPythonGUIInputOutput;
    procedure DataModuleCreate(Sender: TObject);
    procedure DataModuleDestroy(Sender: TObject);
  private
    FLanguage: String;
    jsondata:TJSONData;
    FWaptConfigFileName: String;
    procedure LoadJson(data: UTF8String);
    procedure SetWaptConfigFileName(AValue: String);
    procedure SetLanguage(AValue: String);

    { private declarations }
  public
    { public declarations }
    WAPT:Variant;

    property WaptConfigFileName:String read FWaptConfigFileName write SetWaptConfigFileName;
    function RunJSON(expr: UTF8String; jsonView: TVirtualJSONInspector=
      nil): ISuperObject;

    property Language:String read FLanguage write SetLanguage;
  end;

var
  DMPython: TDMPython;

implementation
uses waptcommon,inifiles,forms,controls;
{$R *.lfm}

procedure TDMPython.SetWaptConfigFileName(AValue: String);
var
  St:TStringList;
  ini : TInifile;
  i: integer;
begin
  if FWaptConfigFileName=AValue then
    Exit;

  FWaptConfigFileName:=AValue;
  if AValue<>'' then
  try
    Screen.Cursor:=crHourGlass;
    if not DirectoryExists(ExtractFileDir(AValue)) then
      mkdir(ExtractFileDir(AValue));
    //Initialize waptconsole parameters with local workstation wapt-get parameters...
    if not FileExists(AValue) then
      CopyFile(WaptIniFilename,AValue);
    st := TStringList.Create;
    try
      st.Append('import logging');
      st.Append('import requests');
      st.Append('import json');
      st.Append('import os');
      st.Append('import common');
      st.Append('import waptpackage');
      st.Append('import waptdevutils');
      st.Append('import setuphelpers');
      st.Append('from common import jsondump');
      st.Append('logger = logging.getLogger()');
      st.Append('logging.basicConfig(level=logging.WARNING)');
      st.Append(format('mywapt = common.Wapt(config_filename=r"%s".decode(''utf8''),disable_update_server_status=True)',[AValue]));
      st.Append('mywapt.dbpath=r":memory:"');
      st.Append('mywapt.use_hostpackages = False');
      //st.Append('mywapt.update(register=False)');
      PythonEng.ExecStrings(St);
      WAPT:=MainModule.mywapt;
    finally
      st.free;
    end;
    // override lang setting
    for i := 1 to Paramcount - 1 do
      if (ParamStrUTF8(i) = '--LANG') or (ParamStrUTF8(i) = '-l') or
        (ParamStrUTF8(i) = '--lang') then
        begin
          waptcommon.Language := ParamStrUTF8(i + 1);
          waptcommon.FallBackLanguage := copy(waptcommon.Language,1,2);
          Language:=FallBackLanguage;
        end;

    // get from ini
    if Language = '' then
    begin
      ini := TIniFile.Create(FWaptConfigFileName);
      try
        waptcommon.Language := ini.ReadString('global','language','');
        waptcommon.FallBackLanguage := copy(waptcommon.Language,1,2);
        Language := waptcommon.Language;
      finally
        ini.Free;
      end;
    end;
  finally
    Screen.Cursor:=crDefault;
  end;
end;

procedure TDMPython.SetLanguage(AValue: String);
begin
  if FLanguage=AValue then Exit;
  FLanguage:=AValue;
  SetDefaultLang(FLanguage);
  if FLanguage='fr' then
    GetLocaleFormatSettings($1252, DefaultFormatSettings)
  else
    GetLocaleFormatSettings($409, DefaultFormatSettings);

end;

procedure TDMPython.DataModuleCreate(Sender: TObject);

begin
  with PythonEng do
  begin
    DllName := 'python27.dll';
    RegVersion := '2.7';
    UseLastKnownVersion := False;
    LoadDLL;
    Py_SetProgramName(PAnsiChar(ParamStr(0)));
  end;

end;

procedure TDMPython.DataModuleDestroy(Sender: TObject);
begin
  if Assigned(jsondata) then
    FreeAndNil(jsondata);

end;

function TDMPython.RunJSON(expr: UTF8String; jsonView: TVirtualJSONInspector=Nil): ISuperObject;
var
  res:UTF8String;
begin
  if Assigned(jsonView) then
    jsonView.Clear;

  res := PythonEng.EvalStringAsStr(format('jsondump(%s)',[expr]));
  result := SO( UTF8Decode(res) );

  if Assigned(jsonView) then
  begin
    LoadJson(res);
    jsonView.RootData := jsondata;
  end;

end;

procedure TDMPython.LoadJson(data: UTF8String);
var
  P:TJSONParser;
begin
  P:=TJSONParser.Create(Data,True);
  try
    if jsondata<>Nil then
      FreeAndNil(jsondata);
    jsondata := P.Parse;
  finally
      FreeAndNil(P);
  end;
end;



end.

