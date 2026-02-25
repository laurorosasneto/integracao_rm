  SELECT DISTINCT SMATRICULA.RA                     as USERNAME
                                         , 'rm'                                auth
                                         , SMATRICULA.RA                     as PASSWORD
                                         , UPPER(CASE
                                                     WHEN CHARINDEX(' ', LTRIM(RTRIM(PPESSOA.NOME))) > 0 THEN LEFT(PPESSOA.NOME,
                                                                                                                   CHARINDEX(' ', LTRIM(RTRIM(PPESSOA.NOME))) -
                                                                                                                   1)
                                                     ELSE PPESSOA.NOME END)  AS FIRSTNAME
                                         , SUBSTRING(LTRIM(RTRIM(PPESSOA.NOME)), CHARINDEX(' ', LTRIM(RTRIM(PPESSOA.NOME))) + 1,
                                                     50)                        LASTNAME
                                         , LOWER(CASE
                                                     WHEN PPESSOA.EMAIL IS NULL or PPESSOA.EMAIL = ''
                                                         THEN CONCAT(SALUNO.RA, '@default.com.br')
                                                     ELSE PPESSOA.EMAIL END) AS EMAIL
                                         , CPF                               AS profile_field_CPF
                                      /*   , CASE
                                               WHEN STIPMODAHAB = 1 THEN 'PRESENCIAL'
                                               WHEN STIPMODAHAB = 2 THEN 'SEMI-PRESENCIAL'
                                               WHEN STIPMODAHAB = 3 THEN 'EAD'
                                               WHEN STIPMODAHAB = 4 THEN 'HIBRIDO'
                       END                                                   AS profile_field_MODALIDADE
                                         , STIPOCURSO.NOME                   AS profile_field_NIVEL_ENSINO
                                         , SCURSO.NOME                       AS profile_field_curso
                                         , CASE
                                               WHEN PPESSOA.TELEFONE1 IS NULL OR PPESSOA.TELEFONE1 = '' THEN
                                                   case
                                                       WHEN PPESSOA.TELEFONE2 IS NULL OR PPESSOA.TELEFONE2 = '' THEN
                                                           case
                                                               WHEN PPESSOA.TELEFONE3 IS NULL OR PPESSOA.TELEFONE3 = ''
                                                                   THEN PPESSOA.TELEFONE1
                                                               ELSE PPESSOA.TELEFONE3
                                                               END
                                                       ELSE PPESSOA.TELEFONE2
                                                       END
                                               ELSE PPESSOA.TELEFONE1
                       END                                                   AS profile_field_telefone
                                         , '20261'                              profile_field_periodo*/
               
               
                                    FROM STURMADISC (NOLOCK)
                                             LEFT JOIN STURMADISCCOMPL (NOLOCK)
                                                       ON STURMADISCCOMPL.CODCOLIGADA = STURMADISC.CODCOLIGADA AND
                                                          STURMADISCCOMPL.IDTURMADISC = STURMADISC.IDTURMADISC
                                             INNER JOIN SPLETIVO (NOLOCK) ON STURMADISC.CODCOLIGADA = SPLETIVO.CODCOLIGADA AND
                                                                             SPLETIVO.IDPERLET = STURMADISC.IDPERLET
                                             INNER JOIN SDISCIPLINA (NOLOCK) ON STURMADISC.CODCOLIGADA = SDISCIPLINA.CODCOLIGADA AND
                                                                                STURMADISC.CODDISC = SDISCIPLINA.CODDISC
                                             INNER JOIN SMATRICULA (NOLOCK) ON STURMADISC.CODCOLIGADA = SMATRICULA.CODCOLIGADA AND
                                                                               STURMADISC.IDTURMADISC = SMATRICULA.IDTURMADISC
                                             INNER JOIN SSTATUS (NOLOCK) ON SSTATUS.CODCOLIGADA = SMATRICULA.CODCOLIGADA AND
                                                                            SSTATUS.CODSTATUS = SMATRICULA.CODSTATUS
                                             INNER JOIN ZMDSSTATUSSTATUSGLOBAL (NOLOCK)
                                                        ON SSTATUS.CODCOLIGADA = ZMDSSTATUSSTATUSGLOBAL.CODCOLIGADA AND
                                                           SSTATUS.CODSTATUS = ZMDSSTATUSSTATUSGLOBAL.CODSTATUS
                                             INNER JOIN SMATRICPL (NOLOCK) ON SMATRICPL.CODCOLIGADA = SMATRICULA.CODCOLIGADA AND
                                                                              SMATRICPL.RA = SMATRICULA.RA AND
                                                                              SMATRICPL.IDPERLET = SMATRICULA.IDPERLET AND
                                                                              SMATRICPL.IDHABILITACAOFILIAL =
                                                                              SMATRICULA.IDHABILITACAOFILIAL
                                             LEFT JOIN SSTATUS STATUS_PERIODO (NOLOCK)
                                                       ON STATUS_PERIODO.CODCOLIGADA = SMATRICPL.CODCOLIGADA AND
                                                          STATUS_PERIODO.CODSTATUS = SMATRICPL.CODSTATUS
                                             INNER JOIN ZMDSSTATUSSTATUSGLOBAL Z (NOLOCK)
                                                        ON STATUS_PERIODO.CODCOLIGADA = Z.CODCOLIGADA AND
                                                           STATUS_PERIODO.CODSTATUS = Z.CODSTATUS
                                             INNER JOIN SALUNO (NOLOCK)
                                                        ON SALUNO.CODCOLIGADA = SMATRICPL.CODCOLIGADA AND SALUNO.RA = SMATRICPL.RA
                                             INNER JOIN PPESSOA (NOLOCK) ON PPESSOA.CODIGO = SALUNO.CODPESSOA
                                             INNER JOIN SHABILITACAOFILIAL (NOLOCK)
                                                        ON SHABILITACAOFILIAL.CODCOLIGADA = SMATRICPL.CODCOLIGADA AND
                                                           SHABILITACAOFILIAL.IDHABILITACAOFILIAL = SMATRICPL.IDHABILITACAOFILIAL
                                             INNER JOIN SHABILITACAO (NOLOCK)
                                                        ON SHABILITACAOFILIAL.CODCOLIGADA = SHABILITACAO.CODCOLIGADA AND
                                                           SHABILITACAOFILIAL.CODCURSO = SHABILITACAO.CODCURSO AND
                                                           SHABILITACAOFILIAL.CODHABILITACAO = SHABILITACAO.CODHABILITACAO
                                             INNER JOIN SHABILITACAOCOMPL (NOLOCK)
                                                        ON SHABILITACAO.CODCOLIGADA = SHABILITACAOCOMPL.CODCOLIGADA and
                                                           SHABILITACAO.CODCURSO = SHABILITACAOCOMPL.CODCURSO and
                                                           SHABILITACAO.CODHABILITACAO = SHABILITACAOCOMPL.CODHABILITACAO
                                             INNER JOIN SCURSO (NOLOCK) ON SCURSO.CODCOLIGADA = SHABILITACAOFILIAL.CODCOLIGADA AND
                                                                           SCURSO.CODCURSO = SHABILITACAOFILIAL.CODCURSO
                                             INNER JOIN STIPOCURSO (NOLOCK)
                                                        ON STIPOCURSO.CODCOLIGADA = SHABILITACAOFILIAL.CODCOLIGADA AND
                                                           STIPOCURSO.CODTIPOCURSO = SHABILITACAOFILIAL.CODTIPOCURSO
                                             LEFT JOIN STIPOALUNO (NOLOCK) ON STIPOALUNO.CODCOLIGADA = SALUNO.CODCOLIGADA AND
                                                                              STIPOALUNO.CODTIPOALUNO = SALUNO.CODTIPOALUNO AND
                                                                              STIPOALUNO.CODTIPOCURSO = STIPOCURSO.CODTIPOCURSO
               
                                    WHERE CODPERLET IN ('2026/1')
                                      AND Z.IDSTATUSGLOBAL in (1, 28)
                                      AND NOT ( SHABILITACAOFILIAL.CODTIPOCURSO in (1, 15, 16,17,18,19)) /*ALUNOS DA FST E FAMEC SÃO DE OUTRO AMBIENTE*/
                                      /*AND NOT (SMATRICULA.CODCOLIGADA = 3 AND SHABILITACAOFILIAL.CODTIPOCURSO = 12 AND SMATRICPL.CODFILIAL = 4)*/
									  /*AND SMATRICULA.CODCOLIGADA = 3*/